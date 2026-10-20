//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  SearchCore.cpp
//
//  Written for ES-DE-Plus. Indexed library search with mutable ranking state.
//

#include "search/SearchCore.h"

#include <algorithm>
#ifdef SEARCH_TEST_BUILD_TIMING
#include <chrono>
#include <cstdio>
#include <cstdlib>
#endif
#include <array>
#include <atomic>
#include <functional>
#include <map>
#include <numeric>
#include <queue>
#include <set>
#include <stdexcept>
#include <string_view>
#include <unicode/normalizer2.h>
#include <unicode/uchar.h>
#include <unicode/uscript.h>
#include <unicode/utf8.h>
#include <unordered_map>
#include <unordered_set>

namespace LibrarySearch
{
    namespace
    {
        bool starts(std::string_view text, std::string_view prefix)
        {
            return text.size() >= prefix.size() && text.substr(0, prefix.size()) == prefix;
        }

        uint32_t gram(std::string_view text, size_t offset, size_t length)
        {
            uint32_t key {static_cast<uint32_t>(length) << 24};
            for (size_t n {0}; n < length; ++n)
                key |= static_cast<uint32_t>(static_cast<unsigned char>(text[offset + n]))
                       << (8 * n);
            return key;
        }

        struct Folded {
            std::string text;
            std::vector<Span> source;
            uint8_t article {0};
        };

        Folded fold(std::string_view input, bool mapping = false)
        {
            Folded out;
            out.text.reserve(input.size());
            if (mapping)
                out.source.reserve(input.size());
            auto append = [&](const std::string& s, size_t begin, size_t end) {
                out.text += s;
                if (mapping)
                    out.source.insert(out.source.end(), s.size(), Span {begin, end});
            };
            auto space = [&](size_t begin, size_t end) {
                if (!out.text.empty() && out.text.back() != ' ') {
                    out.text.push_back(' ');
                    if (mapping)
                        out.source.push_back({begin, end});
                }
            };
            bool latin {false};
            for (int32_t i {0}; i < static_cast<int32_t>(input.size());) {
                const size_t begin {static_cast<size_t>(i)};
                UChar32 cp;
                U8_NEXT(input.data(), i, static_cast<int32_t>(input.size()), cp);
                const size_t end {static_cast<size_t>(i)};
                if (cp < 0) {
                    space(begin, end);
                    latin = false;
                    continue;
                }
                if (cp >= 0xff01 && cp <= 0xff5e)
                    cp -= 0xfee0;
                // ASCII is the common build path; ICU is needed only for non-ASCII characters.
                if (cp < 128) {
                    latin = (cp >= 'A' && cp <= 'Z') || (cp >= 'a' && cp <= 'z');
                    if (latin || (cp >= '0' && cp <= '9')) {
                        out.text.push_back(
                            static_cast<char>(cp >= 'A' && cp <= 'Z' ? cp + 32 : cp));
                        if (mapping)
                            out.source.push_back({begin, end});
                    }
                    else if (cp == '&') {
                        space(begin, end);
                        append("and", begin, end);
                        space(begin, end);
                    }
                    else if (cp != '\'')
                        space(begin, end);
                    continue;
                }
                const auto type {u_charType(cp)};
                if (latin && (type == U_NON_SPACING_MARK || type == U_COMBINING_SPACING_MARK)) {
                    // A decomposed Latin accent belongs to the preceding highlighted character.
                    if (mapping && !out.source.empty())
                        out.source.back().end = end;
                    continue;
                }
                if (cp == 0x2019 || cp == 0x2018)
                    continue;
                if (!u_isalnum(cp) && type != U_NON_SPACING_MARK &&
                    type != U_COMBINING_SPACING_MARK) {
                    space(begin, end);
                    latin = false;
                    continue;
                }
                latin = u_getIntPropertyValue(cp, UCHAR_SCRIPT) == USCRIPT_LATIN;
                icu::UnicodeString value;
                value.append(cp);
                value.foldCase();
                if (latin) {
                    UErrorCode error {U_ZERO_ERROR};
                    const auto* nfkd = icu::Normalizer2::getNFKDInstance(error);
                    icu::UnicodeString decomposed;
                    if (U_SUCCESS(error))
                        nfkd->normalize(value, decomposed, error);
                    if (U_SUCCESS(error))
                        value = decomposed;
                }
                std::string bytes;
                for (int32_t n {0}; n < value.length();) {
                    UChar32 c {value.char32At(n)};
                    n += U16_LENGTH(c);
                    if (latin && u_charType(c) == U_NON_SPACING_MARK)
                        continue;
                    switch (c) {
                        case 0x00e6:
                            bytes += "ae";
                            break;
                        case 0x0153:
                            bytes += "oe";
                            break;
                        case 0x00f8:
                            bytes += "o";
                            break;
                        case 0x0142:
                            bytes += "l";
                            break;
                        case 0x0111:
                        case 0x00f0:
                            bytes += "d";
                            break;
                        case 0x00fe:
                            bytes += "th";
                            break;
                        case 0x0127:
                            bytes += "h";
                            break;
                        default:
                            icu::UnicodeString(c).toUTF8String(bytes);
                            break;
                    }
                }
                append(bytes, begin, end);
            }
            if (!out.text.empty() && out.text.back() == ' ') {
                out.text.pop_back();
                if (mapping)
                    out.source.pop_back();
            }
            return out;
        }

        std::string withoutFileTags(std::string_view input)
        {
            // Filename dump/region/revision tags are not title vocabulary. Keep an
            // unmatched delimiter literal rather than dropping the rest of a name.
            std::string result;
            result.reserve(input.size());
            for (size_t at {0}; at < input.size();) {
                if (input[at] != '(' && input[at] != '[') {
                    result += input[at++];
                    continue;
                }
                std::string closing;
                size_t end = at;
                for (; end < input.size(); ++end) {
                    const char c = input[end];
                    if (c == '(' || c == '[')
                        closing += c == '(' ? ')' : ']';
                    else if (c == ')' || c == ']') {
                        if (closing.empty() || closing.back() != c)
                            break;
                        closing.pop_back();
                        if (closing.empty())
                            break;
                    }
                }
                if (end == input.size() || !closing.empty()) {
                    result.append(input.substr(at));
                    break;
                }
                result += ' ';
                at = end + 1;
            }
            const auto begin = result.find_first_not_of(" \t");
            return begin == std::string::npos ?
                       std::string {} :
                       result.substr(begin, result.find_last_not_of(" \t") - begin + 1);
        }

        struct Word {
            std::string text;
            size_t offset;
        };
        std::vector<Word> words(const std::string& text)
        {
            std::vector<Word> result;
            result.reserve(8);
            for (size_t begin {0}; begin < text.size();) {
                size_t end {text.find(' ', begin)};
                if (end == std::string::npos)
                    end = text.size();
                result.push_back({text.substr(begin, end - begin), begin});
                begin = end + 1;
            }
            return result;
        }
        struct WordView {
            std::string_view text;
            size_t offset;
        };
        std::vector<WordView> wordViews(std::string_view text)
        {
            std::vector<WordView> result;
            result.reserve(8);
            for (size_t begin {0}; begin < text.size();) {
                const size_t end = std::min(text.find(' ', begin), text.size());
                result.push_back({text.substr(begin, end - begin), begin});
                begin = end + 1;
            }
            return result;
        }
        bool small(std::string_view word)
        {
            return word == "a" || word == "an" || word == "the" || word == "of" || word == "to" ||
                   word == "and";
        }
        Folded title(std::string_view text, bool mapping = false)
        {
            auto result = fold(text, mapping);
            size_t remove {0};
            uint8_t articleIndex {0};
            for (const std::string article : {"the ", "an ", "a "}) {
                ++articleIndex;
                if (starts(result.text, article)) {
                    remove = article.size();
                    result.article = articleIndex;
                    break;
                }
            }
            if (remove) {
                result.text.erase(0, remove);
                if (mapping)
                    result.source.erase(result.source.begin(), result.source.begin() + remove);
            }
            const size_t comma {text.rfind(',')};
            if (comma != std::string::npos) {
                const std::string article {fold(text.substr(comma + 1)).text};
                if ((article == "the" || article == "an" || article == "a") &&
                    result.text.size() > article.size()) {
                    result.text.resize(result.text.size() - article.size() - 1);
                    if (mapping)
                        result.source.resize(result.text.size());
                }
            }
            return result;
        }
        const std::array<std::string, 21> romans {
            "",   "i",   "ii",   "iii", "iv", "v",   "vi",   "vii",   "viii", "ix", "x",
            "xi", "xii", "xiii", "xiv", "xv", "xvi", "xvii", "xviii", "xix",  "xx"};
        int romanValue(std::string_view text)
        {
            if (text.empty() || text.size() > 5 ||
                (text[0] != 'i' && text[0] != 'v' && text[0] != 'x'))
                return 0;
            for (size_t n {1}; n < romans.size(); ++n)
                if (text == romans[n])
                    return static_cast<int>(n);
            return 0;
        }
        std::string number(const std::string& text)
        {
            const auto value = romanValue(text);
            return value ? std::to_string(value) : text;
        }
        std::string initial(std::string_view word)
        {
            int32_t end {0};
            UChar32 cp;
            U8_NEXT(word.data(), end, static_cast<int32_t>(word.size()), cp);
            return std::string(word.substr(0, end));
        }
        std::vector<std::string> letters(std::string_view word)
        {
            const auto value = romanValue(word);
            if (value)
                return {initial(word), std::string(word), std::to_string(value)};
            if (!word.empty() && std::all_of(word.begin(), word.end(),
                                             [](char c) { return c >= '0' && c <= '9'; })) {
                if (word.size() <= 2) {
                    const int value {word.size() == 1 ? word[0] - '0' :
                                                        (word[0] - '0') * 10 + word[1] - '0'};
                    if (value > 0 && value <= 20)
                        return {std::string(word), romans[value]};
                }
                return {std::string(word)};
            }
            return {initial(word)};
        }
        std::u32string codepoints(std::string_view text)
        {
            std::u32string result;
            for (int32_t i {0}; i < static_cast<int32_t>(text.size());) {
                UChar32 cp;
                U8_NEXT(text.data(), i, static_cast<int32_t>(text.size()), cp);
                result.push_back(cp);
            }
            return result;
        }
        template <typename T> uint64_t signature(const T& word)
        {
            uint64_t bits {0};
            for (auto c : word)
                bits |= uint64_t {1} << (c >= 'a' && c <= 'z' ? c - 'a' :
                                         c >= '0' && c <= '9' ? c - '0' + 26 :
                                                                36 + c % 28);
            return bits;
        }
        size_t bitCount(uint64_t bits)
        {
            size_t count {0};
            while (bits) {
                ++count;
                bits &= bits - 1;
            }
            return count;
        }
        template <typename T> bool near(const T& a, const T& b)
        {
            const size_t threshold {a.size() >= 9 ? 2U : 1U};
            if (a.size() < 5 || a.size() > b.size() + threshold || b.size() > a.size() + threshold)
                return false;
            if (bitCount(signature(a) & ~signature(b)) > threshold)
                return false;
            // Banded optimal-string-alignment distance, including adjacent transpositions.
            const size_t columns = b.size() + 1;
            std::array<size_t, 384> storage;
            std::vector<size_t> large;
            if (columns > 128)
                large.resize(columns * 3);
            size_t* prev = columns > 128 ? large.data() : storage.data();
            size_t* row = prev + (columns > 128 ? columns : 128);
            size_t* before = row + (columns > 128 ? columns : 128);
            std::iota(prev, prev + columns, 0);
            for (size_t i {1}; i <= a.size(); ++i) {
                std::fill(row, row + columns, threshold + 1);
                row[0] = i;
                const size_t first {i > threshold ? i - threshold : 1};
                const size_t last {std::min(b.size(), i + threshold)};
                size_t minimum {threshold + 1};
                for (size_t j {first}; j <= last; ++j) {
                    row[j] = std::min(
                        {prev[j] + 1, row[j - 1] + 1, prev[j - 1] + (a[i - 1] != b[j - 1])});
                    if (i > 1 && j > 1 && a[i - 1] == b[j - 2] && a[i - 2] == b[j - 1])
                        row[j] = std::min(row[j], before[j - 2] + 1);
                    minimum = std::min(minimum, row[j]);
                }
                if (minimum > threshold)
                    return false;
                std::swap(before, prev);
                std::swap(prev, row);
            }
            return prev[b.size()] <= threshold;
        }
        bool nearWords(const std::string& a, const std::string& b)
        {
            const auto ascii = [](const auto& text) {
                return std::all_of(text.begin(), text.end(),
                                   [](unsigned char c) { return c < 128; });
            };
            return ascii(a) && ascii(b) ? near(a, b) : near(codepoints(a), codepoints(b));
        }
        template <typename T> bool visible(const T& g, const Filter& f)
        {
            return g.countAsGame && !g.collection && (f.showHidden || !g.hidden) &&
                   (!f.kidMode || g.kid) && (!f.favouritesOnly || g.favourite) &&
                   (f.system.empty() || g.system == f.system);
        }
        void mergeSpans(std::vector<Span>& spans)
        {
            std::sort(spans.begin(), spans.end(), [](Span a, Span b) { return a.begin < b.begin; });
            size_t n {0};
            for (auto s : spans) {
                if (n && s.begin <= spans[n - 1].end)
                    spans[n - 1].end = std::max(spans[n - 1].end, s.end);
                else
                    spans[n++] = s;
            }
            spans.resize(n);
        }
        std::string compact(std::string text)
        {
            text.erase(std::remove(text.begin(), text.end(), ' '), text.end());
            return text;
        }
        Filter normalizedFilter(Filter filter)
        {
            filter.genre = compact(normalize(filter.genre));
            filter.developer = compact(normalize(filter.developer));
            filter.publisher = compact(normalize(filter.publisher));
            return filter;
        }
        bool validDate(const std::string& date)
        {
            return date.size() == 15 && date[8] == 'T' &&
                   std::all_of(date.begin(), date.begin() + 8,
                               [](char c) { return c >= '0' && c <= '9'; }) &&
                   std::all_of(date.begin() + 9, date.end(),
                               [](char c) { return c >= '0' && c <= '9'; });
        }
        bool digits(std::string_view word)
        {
            return !word.empty() && std::all_of(word.begin(), word.end(),
                                                [](char c) { return c >= '0' && c <= '9'; });
        }
        bool numeric(std::string_view word) { return digits(word) || romanValue(word) != 0; }
        struct Text {
            std::string value;
            std::vector<Word> tokens;
            bool literalX {false};
        };
        Text makeText(std::string value)
        {
            auto tokens = words(value);
            return {std::move(value), std::move(tokens)};
        }

        // Each query token uses a distinct word. Augmenting paths handle ambiguous prefixes
        // ("ma mario" against "Mario Maker") without factorial permutation searches.
        bool wordMatch(const std::vector<Word>& query,
                       const Text& t,
                       int mode,
                       std::vector<Span>* spans)
        {
            if (query.size() > t.tokens.size())
                return false;
            auto accepts = [&](size_t q, size_t w) {
                const auto& target = t.tokens[w].text;
                const auto& token = query[q].text;
                if (target == "x" && t.literalX && digits(token))
                    return false;
                if (numeric(token))
                    return numeric(target) &&
                           (mode >= 2 ? number(target) == number(token) : target == token);
                if (mode == 3)
                    return starts(target, token) || (!digits(target) && nearWords(token, target));
                return starts(target, token);
            };
            if ((mode == 0 || mode == 4) && !spans) {
                size_t w {0};
                for (size_t q {0}; q < query.size(); ++q) {
                    while (w < t.tokens.size() && !accepts(q, w))
                        ++w;
                    if (w == t.tokens.size())
                        return false;
                    ++w;
                }
                return true;
            }
            std::vector<int> owner(t.tokens.size(), -1);
            if (mode == 0 || mode == 4) {
                size_t w {0};
                for (size_t q {0}; q < query.size(); ++q) {
                    while (w < t.tokens.size() && !accepts(q, w))
                        ++w;
                    if (w == t.tokens.size())
                        return false;
                    owner[w++] = static_cast<int>(q);
                }
            }
            else {
                std::function<bool(size_t, std::vector<bool>&)> assign =
                    [&](size_t q, std::vector<bool>& seen) {
                        for (size_t w {0}; w < t.tokens.size(); ++w) {
                            if (seen[w] || !accepts(q, w))
                                continue;
                            seen[w] = true;
                            if (owner[w] < 0 || assign(owner[w], seen)) {
                                owner[w] = static_cast<int>(q);
                                return true;
                            }
                        }
                        return false;
                    };
                for (size_t q {0}; q < query.size(); ++q) {
                    std::vector<bool> seen(t.tokens.size());
                    if (!assign(q, seen))
                        return false;
                }
            }
            if (spans)
                for (size_t w {0}; w < owner.size(); ++w)
                    if (owner[w] >= 0) {
                        const auto& word {t.tokens[w]};
                        const auto& q {query[owner[w]].text};
                        spans->push_back(
                            {word.offset, word.offset + (mode >= 2 ? word.text.size() : q.size())});
                    }
            return true;
        }

        bool acronym(const std::string& query, const Text& title, std::vector<Span>* spans)
        {
            if (query.size() < 2)
                return false;
            const auto& ws = title.tokens;
            size_t maximum {0};
            bool possibleStart {false};
            for (const auto& w : ws) {
                if (!numeric(w.text)) {
                    maximum += initial(w.text).size();
                    possibleStart |= w.text.front() == query.front();
                }
                else {
                    size_t length {0};
                    for (const auto& v : letters(w.text)) {
                        length = std::max(length, v.size());
                        possibleStart |= v.front() == query.front();
                    }
                    maximum += length;
                }
            }
            if (!possibleStart || query.size() > maximum)
                return false;
            auto variants = [&](const std::string& word) {
                return title.literalX && word == "x" ? std::vector<std::string> {"x"} :
                                                       letters(word);
            };
            const size_t width {query.size() + 1};
            // Bottom-up states (word, query byte, consumed words capped at two). Shared
            // suffixes keep long runs of optional small words linear and avoid recursion.
            std::vector<std::array<uint8_t, 3>> states((ws.size() + 1) * width);
            for (size_t w {0}; w <= ws.size(); ++w)
                states[w * width + query.size()][2] = 1;
            for (size_t w {ws.size()}; w-- > 0;) {
                const auto choices = variants(ws[w].text);
                for (size_t p {0}; p < query.size(); ++p)
                    for (size_t used {0}; used < 3; ++used) {
                        bool found {small(ws[w].text) && states[(w + 1) * width + p][used]};
                        for (const auto& s : choices)
                            if (s.size() <= query.size() - p &&
                                query.compare(p, s.size(), s) == 0 &&
                                states[(w + 1) * width + p + s.size()]
                                      [std::min(size_t {2}, used + 1)]) {
                                found = true;
                                break;
                            }
                        states[w * width + p][used] = found;
                    }
            }
            size_t start {0};
            while (start < ws.size() && !states[start * width][0])
                ++start;
            if (start == ws.size())
                return false;
            if (!spans)
                return true;
            size_t p {0}, used {0};
            for (size_t w {start}; w < ws.size() && p < query.size(); ++w) {
                for (const auto& s : variants(ws[w].text)) {
                    if (s.size() > query.size() - p || query.compare(p, s.size(), s) != 0 ||
                        !states[(w + 1) * width + p + s.size()][std::min(size_t {2}, used + 1)])
                        continue;
                    const auto length {s == initial(ws[w].text) ? s.size() : ws[w].text.size()};
                    spans->push_back({ws[w].offset, ws[w].offset + length});
                    p += s.size();
                    used = std::min(size_t {2}, used + 1);
                    break;
                }
            }
            return true;
        }
        int rank(const std::string& q,
                 const std::vector<Word>& qw,
                 const Text& t,
                 std::vector<Span>* spans = nullptr,
                 int wanted = -1)
        {
            const bool compactNeeded = wanted < 0 || wanted == 0 || wanted == 1 || wanted == 6;
            const auto cq = compactNeeded ? compact(q) : std::string {};
            const auto ct = compactNeeded ? compact(t.value) : std::string {};
            auto compactSpan = [&](size_t begin, size_t end) {
                if (!spans)
                    return;
                size_t pos {0};
                size_t first {0};
                for (size_t i {0}; i < t.value.size(); ++i) {
                    if (t.value[i] == ' ')
                        continue;
                    if (pos == begin)
                        first = i;
                    ++pos;
                    if (pos == end) {
                        spans->push_back({first, i + 1});
                        break;
                    }
                }
            };
            if ((wanted < 0 || wanted == 0) && cq == ct) {
                compactSpan(0, ct.size());
                return 0;
            }
            const bool hasNumber =
                std::any_of(qw.begin(), qw.end(), [](const auto& w) { return numeric(w.text); });
            if ((wanted < 0 || wanted == 1) && starts(ct, cq) &&
                (!hasNumber || wordMatch(qw, t, 4, nullptr))) {
                compactSpan(0, cq.size());
                return 1;
            }
            if ((wanted < 0 || wanted == 5) && hasNumber && !wordMatch(qw, t, 0, nullptr) &&
                wordMatch(qw, t, 4, spans))
                return 5;
            if ((wanted < 0 || wanted == 2) && wordMatch(qw, t, 0, spans))
                return 2;
            if ((wanted < 0 || wanted == 3) && wordMatch(qw, t, 1, spans))
                return 3;
            if (wanted < 0 || wanted == 4) {
                bool abbreviations {true};
                bool usedAcronym {false};
                std::vector<Span> abbreviated;
                for (const auto& w : qw) {
                    auto pos =
                        std::find_if(t.tokens.begin(), t.tokens.end(), [&](const Word& word) {
                            return numeric(w.text) ?
                                       numeric(word.text) && number(word.text) == number(w.text) :
                                       starts(word.text, w.text);
                        });
                    if (pos != t.tokens.end()) {
                        if (spans)
                            abbreviated.push_back(
                                {pos->offset, pos->offset + (numeric(w.text) ? pos->text.size() :
                                                                               w.text.size())});
                    }
                    else {
                        if (numeric(w.text) ||
                            !acronym(w.text, t, spans ? &abbreviated : nullptr)) {
                            abbreviations = false;
                            break;
                        }
                        usedAcronym = true;
                    }
                }
                if (abbreviations && usedAcronym) {
                    if (spans)
                        *spans = std::move(abbreviated);
                    return 4;
                }
            }
            if ((wanted < 0 || wanted == 5) && wordMatch(qw, t, 2, spans))
                return 5;
            const auto pos {ct.find(cq)};
            const bool numericSubstring =
                (wanted < 0 || wanted == 6) && pos != std::string::npos &&
                (!hasNumber || std::all_of(qw.begin(), qw.end(), [&](const auto& w) {
                    if (!numeric(w.text))
                        return true;
                    return std::any_of(t.tokens.begin(), t.tokens.end(), [&](const auto& target) {
                        return number(target.text) == number(w.text) ||
                               (&w == &qw.back() && digits(w.text) && starts(target.text, w.text));
                    });
                }));
            if ((wanted < 0 || wanted == 6) && pos != std::string::npos && numericSubstring) {
                compactSpan(pos, pos + cq.size());
                return 6;
            }
            if ((wanted < 0 || wanted == 7) && wordMatch(qw, t, 3, spans))
                return 7;
            return -1;
        }
    } // namespace

    std::string normalize(const std::string& text) { return fold(text).text; }
    namespace
    {
        std::atomic<uint64_t> nextVersion {1};
    }

    struct Core::Index {
        using Id = uint32_t;
        struct Range {
            Id begin {0}, count {0};
        };
        struct Ref {
            Id begin {0}, size {0};
        };
        struct Document {
            Ref text, compact;
            Id game;
        };
        struct Vocabulary {
            Ref text;
            uint64_t bits;
            Range documents;
            Id length;
            Id completion {UINT32_MAX};
        };
        struct Completion {
            SuggestionKind kind;
            Id key;
            Range games;
            uint32_t weight;
        };
        struct Entity {
            std::string key;
            SuggestionKind kind;
            std::string compact;
            std::vector<std::string> aliases;
        };
        struct Postings {
            struct Slot {
                Id key {0};
                Range range;
            };
            std::vector<Slot> slots;
            std::vector<Id> values;
            size_t used {0};
            static size_t position(Id key, size_t mask)
            {
                key ^= key >> 16;
                key *= 0x9e3779b1U;
                key ^= key >> 13;
                return key & mask;
            }
            size_t locate(Id key) const
            {
                size_t at = position(key, slots.size() - 1);
                while (slots[at].key && slots[at].key != key)
                    at = (at + 1) & (slots.size() - 1);
                return at;
            }
            void grow()
            {
                auto old = std::move(slots);
                slots.resize(old.empty() ? 64 : old.size() * 2);
                for (const auto& entry : old)
                    if (entry.key)
                        slots[locate(entry.key)] = entry;
            }
            Range& insert(Id key)
            {
                if (slots.empty())
                    grow();
                auto at = locate(key);
                if (slots[at].key)
                    return slots[at].range;
                if ((used + 1) * 2 > slots.size()) {
                    grow();
                    at = locate(key);
                }
                slots[at].key = key;
                ++used;
                return slots[at].range;
            }
            void build(std::vector<uint64_t> pairs)
            {
                // Callers append in increasing value-id order. Stable counting
                // buckets preserve that order without sorting all key/id pairs.
                for (auto pair : pairs)
                    ++insert(pair >> 32).count;
                std::vector<Id> cursor(slots.size());
                Id count {0};
                for (size_t n {0}; n < slots.size(); ++n)
                    if (slots[n].key) {
                        auto& range = slots[n].range;
                        range.begin = count;
                        cursor[n] = count;
                        count += range.count;
                    }
                values.resize(pairs.size());
                for (auto pair : pairs)
                    values[cursor[locate(pair >> 32)]++] = static_cast<Id>(pair);
                Id output {0};
                for (auto& entry : slots)
                    if (entry.key) {
                        auto& range = entry.range;
                        const Id begin = range.begin, end = begin + range.count;
                        range.begin = output;
                        Id previous {0};
                        for (Id at = begin; at < end; ++at) {
                            const Id value = values[at];
                            if (at == begin || value != previous)
                                values[output++] = value;
                            previous = value;
                        }
                        range.count = output - range.begin;
                    }
                values.resize(output);
            }
            void append(Id key, std::vector<Id>& out) const
            {
                if (slots.empty())
                    return;
                const auto& entry = slots[locate(key)];
                if (entry.key)
                    out.insert(out.end(), values.begin() + entry.range.begin,
                               values.begin() + entry.range.begin + entry.range.count);
            }
        };
        struct Record {
            Ref id, title, sortName, fileStem, developer, publisher, genre, system, systemName;
            uint64_t lastPlayed;
            int playCount;
            uint32_t titleLength;
            bool favourite, hidden, kid, countAsGame, collection;
            uint8_t article {0};
        };
        struct GameView {
            std::string_view id, title, sortName, fileStem, developer, publisher, genre, system,
                systemName;
            uint64_t lastPlayed;
            int playCount;
            bool favourite, hidden, kid, countAsGame, collection;
        };
        static uint64_t date(std::string_view value)
        {
            uint64_t result {0};
            for (char c : value)
                if (c != 'T')
                    result = result * 10 + c - '0';
            return result;
        }
        static std::string dateText(uint64_t value)
        {
            if (!value)
                return "0";
            std::string result(14, '0');
            for (size_t n {14}; n-- > 0;) {
                result[n] = static_cast<char>('0' + value % 10);
                value /= 10;
            }
            result.insert(8, "T");
            return result;
        }
        std::vector<Record> games;
        std::string rawText;
        GameView get(Id id) const
        {
            const auto& g = games[id];
            return {view(g.id, rawText),
                    view(g.title, rawText),
                    view(g.sortName, rawText),
                    view(g.fileStem, rawText),
                    view(g.developer, rawText),
                    view(g.publisher, rawText),
                    view(g.genre, rawText),
                    view(g.system, rawText),
                    view(g.systemName, rawText),
                    g.lastPlayed,
                    g.playCount,
                    g.favourite,
                    g.hidden,
                    g.kid,
                    g.countAsGame,
                    g.collection};
        }
        bool allowed(Id id, const Filter& filter) const
        {
            const auto& g = games[id];
            const auto entityMatches = [&](size_t slot, const std::string& value) {
                const Id entity = gameEntities[id][slot];
                return value.empty() || (entity != UINT32_MAX && entities[entity].key == value);
            };
            return (filter.showHidden || !g.hidden) && (!filter.kidMode || g.kid) &&
                   (!filter.favouritesOnly || g.favourite) &&
                   (filter.system.empty() || view(g.system, rawText) == filter.system) &&
                   entityMatches(0, filter.developer) && entityMatches(1, filter.publisher) &&
                   entityMatches(2, filter.genre);
        }
        std::string text, compactText, wordText;
        std::vector<Document> documents;
        std::vector<std::array<Id, 3>> gameDocuments;
        std::vector<std::array<Id, 4>> gameEntities;
        std::vector<Vocabulary> vocabulary;
        std::vector<Id> wordOrder, documentOrder, wordDocuments, rankingOrder, rankingPosition;
        Postings wordGrams, boundaries, initials;
        std::array<std::vector<Id>, 64> characterWords;
        std::vector<Entity> entities;
        std::vector<Completion> completions;
        std::vector<Id> support;
        std::array<std::vector<Id>, 7> completionOrder;
        std::map<std::string, std::set<std::string>> systems;
        std::map<std::string, std::vector<Id>> articles;
        std::set<std::pair<uint64_t, Id>> played;
        std::vector<uint8_t> recent, letterX;
        Text textFor(Id d) const
        {
            auto value = makeText(std::string(doc(d)));
            value.literalX = letterX[documents[d].game];
            return value;
        }
        static void unique(std::vector<Id>& ids)
        {
            std::sort(ids.begin(), ids.end());
            ids.erase(std::unique(ids.begin(), ids.end()), ids.end());
        }
        static Ref append(std::string& pool, std::string_view value)
        {
            Ref ref {static_cast<Id>(pool.size()), static_cast<Id>(value.size())};
            pool.append(value.data(), value.size());
            return ref;
        }
        std::string_view view(Ref r, const std::string& pool) const
        {
            return {pool.data() + r.begin, r.size};
        }
        std::string_view doc(Id id) const { return view(documents[id].text, text); }
        std::string_view joined(Id id) const { return view(documents[id].compact, compactText); }
        std::string_view word(Id id) const { return view(vocabulary[id].text, wordText); }
        std::string_view key(Id id) const
        {
            const auto& c = completions[id];
            if (c.kind == SuggestionKind::Word)
                return word(c.key);
            if (c.kind == SuggestionKind::Title)
                return joined(c.key);
            return entities[c.key].compact;
        }
        bool entityMatches(Id completion, const std::string& query) const
        {
            const auto& c = completions[completion];
            if (key(completion).find(query) != std::string_view::npos)
                return true;
            return c.kind == SuggestionKind::System &&
                   std::any_of(entities[c.key].aliases.begin(), entities[c.key].aliases.end(),
                               [&](const std::string& alias) {
                                   return alias.find(query) != std::string::npos;
                               });
        }
        // Compare normalized strings with separators ignored without storing another copy.
        static int compare(std::string_view a, std::string_view b)
        {
            size_t x {0}, y {0};
            while (true) {
                while (x < a.size() && a[x] == ' ')
                    ++x;
                while (y < b.size() && b[y] == ' ')
                    ++y;
                if (x == a.size() || y == b.size())
                    return (x < a.size()) - (y < b.size());
                if (a[x] != b[y])
                    return static_cast<unsigned char>(a[x]) < static_cast<unsigned char>(b[y]) ?
                               -1 :
                               1;
                ++x;
                ++y;
            }
        }
        static bool prefix(std::string_view a, std::string_view b)
        {
            size_t x {0}, y {0};
            while (true) {
                while (x < a.size() && a[x] == ' ')
                    ++x;
                while (y < b.size() && b[y] == ' ')
                    ++y;
                if (y == b.size())
                    return true;
                if (x == a.size() || a[x++] != b[y++])
                    return false;
            }
        }
        // Most library words/titles differ in their first eight UTF-8 bytes.
        // Sorting cached prefixes avoids random arena lookups for those comparisons.
        template <typename Key> static void orderText(std::vector<Id>& ids, Key key)
        {
            struct Entry {
                uint64_t prefix;
                Id id;
            };
            std::vector<Entry> entries;
            entries.reserve(ids.size());
            for (Id id : ids) {
                const auto text = key(id);
                uint64_t prefix {0};
                for (size_t n {0}; n < std::min(size_t {8}, text.size()); ++n)
                    prefix |= uint64_t {static_cast<unsigned char>(text[n])} << (56 - n * 8);
                entries.push_back({prefix, id});
            }
            std::sort(entries.begin(), entries.end(), [&](const Entry& a, const Entry& b) {
                return a.prefix != b.prefix ? a.prefix < b.prefix : key(a.id) < key(b.id);
            });
            for (size_t n {0}; n < ids.size(); ++n)
                ids[n] = entries[n].id;
        }
        bool better(Id a, Id b) const { return rankingPosition[a] < rankingPosition[b]; }
        bool precedes(Id a, Id b) const
        {
            const auto x = get(a);
            const auto y = get(b);
            if (x.favourite != y.favourite)
                return x.favourite;
            if (x.lastPlayed != y.lastPlayed)
                return x.lastPlayed > y.lastPlayed;
            if (x.playCount != y.playCount)
                return x.playCount > y.playCount;
            if (games[a].titleLength != games[b].titleLength)
                return games[a].titleLength < games[b].titleLength;
            // Sort-name/system folding is already present in the document arena.
            const auto xs = doc(gameDocuments[a][1]), ys = doc(gameDocuments[b][1]);
            if (xs != ys)
                return xs < ys;
            if (x.systemName != y.systemName)
                return x.systemName < y.systemName;
            return x.id < y.id;
        }
        uint32_t boost(Id game) const
        {
            return 1 + (games[game].favourite ? 4 : 0) + (recent[game] ? 2 : 0);
        }
        void appendWord(Id id, std::vector<Id>& out) const
        {
            const auto r = vocabulary[id].documents;
            out.insert(out.end(), wordDocuments.begin() + r.begin,
                       wordDocuments.begin() + r.begin + r.count);
        }
        std::vector<Id> expand(const std::vector<Id>& games) const
        {
            std::vector<Id> result;
            result.reserve(games.size() * 2);
            for (Id d : games) {
                const auto& docs = gameDocuments[documents[d].game];
                result.push_back(docs[0]);
                if (docs[1] != docs[0])
                    result.push_back(docs[1]);
                if (docs[2] != docs[0] && docs[2] != docs[1])
                    result.push_back(docs[2]);
            }
            return result;
        }
        std::vector<Id> prefixCandidates(const std::vector<Word>& query) const
        {
            std::vector<Id> result;
            bool first {true};
            for (const auto& token : query) {
                std::vector<Id> ids;
                auto begin = std::lower_bound(
                    wordOrder.begin(), wordOrder.end(), token.text,
                    [&](Id id, const std::string& value) { return word(id) < value; });
                for (auto it = begin; it != wordOrder.end() && starts(word(*it), token.text);
                     ++it) {
                    if (numeric(token.text) && word(*it) != token.text)
                        continue;
                    appendWord(*it, ids);
                }
                if (numeric(token.text)) {
                    const auto value = number(token.text);
                    for (size_t n {1}; n < romans.size(); ++n)
                        if (value == std::to_string(n)) {
                            for (const auto& alias : {romans[n], std::to_string(n)}) {
                                if (alias == token.text)
                                    continue;
                                auto it = std::lower_bound(
                                    wordOrder.begin(), wordOrder.end(), alias,
                                    [&](Id id, const std::string& key) { return word(id) < key; });
                                if (it != wordOrder.end() && word(*it) == alias)
                                    appendWord(*it, ids);
                            }
                            break;
                        }
                }
                unique(ids);
                if (first) {
                    result = std::move(ids);
                    first = false;
                }
                else {
                    std::vector<Id> intersection;
                    std::set_intersection(result.begin(), result.end(), ids.begin(), ids.end(),
                                          std::back_inserter(intersection));
                    result = std::move(intersection);
                }
                if (result.empty())
                    break;
            }
            return expand(result);
        }
        std::vector<Id> candidates(const std::vector<Word>& query) const
        {
            std::vector<std::vector<Id>> lists;
            for (const auto& token : query) {
                std::vector<Id> ids, wordsFound;
                const auto& q = token.text;
                auto it = std::lower_bound(
                    wordOrder.begin(), wordOrder.end(), q,
                    [&](Id id, const std::string& value) { return word(id) < value; });
                for (; it != wordOrder.end() && starts(word(*it), q); ++it)
                    if (!numeric(q) || digits(q) || word(*it) == q)
                        wordsFound.push_back(*it);
                if (!numeric(q)) {
                    if (q.size() >= 3) {
                        std::vector<Id> grams;
                        wordGrams.append(gram(q, 0, 3), grams);
                        for (Id w : grams) {
                            const auto value = word(w);
                            bool possible = value.find(q) != std::string_view::npos;
                            // A compact substring may continue into the following title word.
                            for (size_t at = value.find(q.substr(0, 3));
                                 !possible && at != std::string_view::npos;
                                 at = value.find(q.substr(0, 3), at + 1))
                                possible = starts(q, value.substr(at));
                            if (possible)
                                wordsFound.push_back(w);
                        }
                        boundaries.append(gram(q, 0, 3), ids);
                    }
                    else if (!digits(q)) {
                        const auto first = codepoints(q).front();
                        const auto bits = signature(std::u32string {first});
                        size_t bit {0};
                        while (!(bits & (uint64_t {1} << bit)))
                            ++bit;
                        for (Id w : characterWords[bit])
                            if (word(w).find(q) != std::string_view::npos)
                                wordsFound.push_back(w);
                    }
                }
                const auto points = codepoints(q);
                const bool digits = !q.empty() && std::all_of(q.begin(), q.end(), [](char c) {
                    return c >= '0' && c <= '9';
                });
                if (points.size() >= 5 && !digits) {
                    const size_t distance = points.size() >= 9 ? 2 : 1;
                    const auto bits = signature(points);
                    std::vector<Id> buckets, possible;
                    for (Id bit {0}; bit < 64; ++bit)
                        if (bits & (uint64_t {1} << bit))
                            buckets.push_back(bit);
                    std::sort(buckets.begin(), buckets.end(), [&](Id a, Id b) {
                        return characterWords[a].size() < characterWords[b].size();
                    });
                    // With at most d edits, at least one of d+1 distinct query
                    // characters survives. If there are fewer, use all of them.
                    for (size_t n {0}; n < std::min(distance + 1, buckets.size()); ++n) {
                        const auto& ids = characterWords[buckets[n]];
                        possible.insert(possible.end(), ids.begin(), ids.end());
                    }
                    unique(possible);
                    for (Id w : possible) {
                        const auto& v = vocabulary[w];
                        if (v.length + distance < points.size() ||
                            v.length > points.size() + distance ||
                            bitCount(bits & ~v.bits) > distance)
                            continue;
                        if (nearWords(q, std::string(word(w))))
                            wordsFound.push_back(w);
                    }
                }
                const auto numberKey = number(q);
                for (size_t n {1}; n < romans.size(); ++n)
                    if (numberKey == std::to_string(n)) {
                        for (const auto& value : {romans[n], std::to_string(n)}) {
                            auto found = std::lower_bound(
                                wordOrder.begin(), wordOrder.end(), value,
                                [&](Id id, const std::string& key) { return word(id) < key; });
                            if (found != wordOrder.end() && word(*found) == value)
                                wordsFound.push_back(*found);
                        }
                        break;
                    }
                unique(wordsFound);
                for (Id w : wordsFound)
                    appendWord(w, ids);
                if (q.size() >= 2 && !numeric(q))
                    initials.append(gram(q, 0, std::min(size_t {3}, q.size())), ids);
                unique(ids);
                if (ids.empty())
                    return {};
                lists.push_back(std::move(ids));
            }
            if (lists.empty())
                return {};
            std::sort(lists.begin(), lists.end(),
                      [](const auto& a, const auto& b) { return a.size() < b.size(); });
            auto result = std::move(lists.front());
            for (size_t i {1}; i < lists.size(); ++i) {
                std::vector<Id> intersection;
                std::set_intersection(result.begin(), result.end(), lists[i].begin(),
                                      lists[i].end(), std::back_inserter(intersection));
                result = std::move(intersection);
                if (result.empty())
                    break;
            }
            return expand(result);
        }
        static bool ordered(const std::vector<Word>& query,
                            std::string_view value,
                            bool equivalent,
                            bool literalX)
        {
            size_t next {0};
            for (const auto& q : query) {
                const bool numeral = numeric(q.text);
                const auto canonical = numeral && equivalent ? number(q.text) : std::string {};
                bool found {false};
                while (next < value.size()) {
                    const size_t end = std::min(value.find(' ', next), value.size());
                    const auto word = value.substr(next, end - next);
                    next = end + 1;
                    bool matches = numeral ? word == q.text : starts(word, q.text);
                    if (numeral && equivalent && !(word == "x" && literalX && digits(q.text))) {
                        const int roman = romanValue(word);
                        matches = roman ? std::to_string(roman) == canonical : word == canonical;
                    }
                    if (matches) {
                        found = true;
                        break;
                    }
                }
                if (!found)
                    return false;
            }
            return true;
        }
        static std::string canonical(std::string_view value)
        {
            std::string result;
            result.reserve(value.size());
            for (size_t at {0}; at < value.size();) {
                const size_t end = std::min(value.find(' ', at), value.size());
                const auto word = value.substr(at, end - at);
                const int roman = romanValue(word);
                if (roman)
                    result += std::to_string(roman);
                else
                    result.append(word.data(), word.size());
                at = end + 1;
            }
            return result;
        }
        struct Result {
            Id game, document;
            int kind, priority;
        };
        static bool containsCompact(std::string_view text, std::string_view query)
        {
            for (size_t begin {0}; begin < text.size(); ++begin) {
                size_t at = begin, matched {0};
                while (at < text.size() && matched < query.size()) {
                    if (text[at] == ' ') {
                        ++at;
                        continue;
                    }
                    if (text[at] != query[matched])
                        break;
                    ++at;
                    ++matched;
                }
                if (matched == query.size())
                    return true;
            }
            return false;
        }
        std::vector<Result> collect(const std::string& query,
                                    size_t limit,
                                    const Filter& filter,
                                    bool metadata,
                                    const std::set<std::string>* restricted = nullptr,
                                    bool complete = false) const
        {
            const auto q = title(query).text;
            const auto qw = words(q);
            const bool substringMembership =
                complete && std::all_of(qw.begin(), qw.end(), [](const Word& w) {
                    return !digits(w.text) && number(w.text) == w.text;
                });
            if (q.empty() || !limit)
                return {};
            auto allowed = [&](Id g) {
                return this->allowed(g, filter) &&
                       (!restricted ||
                        restricted->count(std::string(view(games[g].system, rawText))));
            };
            // Per-thread scratch is reused across queries, including the restricted/full
            // passes. No library-sized allocation or initialization on a keystroke.
            struct Scratch {
                std::vector<uint32_t> stamp, position, metadataStamp;
                std::vector<Result> rows;
                uint32_t epoch {0};
            };
            thread_local Scratch scratch;
            if (scratch.stamp.size() < games.size()) {
                scratch.stamp.resize(games.size());
                scratch.position.resize(games.size());
            }
            if (++scratch.epoch == 0) {
                std::fill(scratch.stamp.begin(), scratch.stamp.end(), 0);
                std::fill(scratch.metadataStamp.begin(), scratch.metadataStamp.end(), 0);
                ++scratch.epoch;
            }
            auto& matches = scratch.rows;
            matches.clear();
            auto find = [&](Id g) -> Result* {
                return scratch.stamp[g] == scratch.epoch ? &matches[scratch.position[g]] : nullptr;
            };
            auto put = [&](Id d, int kind, int priority) {
                const Id g = documents[d].game;
                if (!allowed(g))
                    return;
                auto previous = find(g);
                if (previous) {
                    if (priority < previous->priority)
                        *previous = {g, d, kind, priority};
                }
                else {
                    scratch.stamp[g] = scratch.epoch;
                    scratch.position[g] = matches.size();
                    matches.push_back({g, d, kind, priority});
                }
            };
            const auto compactQuery = compact(q);
            auto begin =
                std::lower_bound(documentOrder.begin(), documentOrder.end(), compactQuery,
                                 [&](Id d, const std::string& value) { return joined(d) < value; });
            bool arabic {false};
            const bool numerals =
                std::any_of(qw.begin(), qw.end(), [](const Word& w) { return numeric(w.text); });
            std::string queryCanonical;
            for (const auto& w : qw)
                if (digits(w.text))
                    arabic = true;
            for (auto it = begin; it != documentOrder.end() && starts(joined(*it), compactQuery);
                 ++it) {
                const bool exact = joined(*it) == compactQuery;
                if (!arabic)
                    put(*it, exact ? 0 : 1, exact ? 0 : 1);
            }
            if (matches.size() < limit || arabic || complete) {
                for (Id d : prefixCandidates(qw)) {
                    if (!allowed(documents[d].game))
                        continue;
                    if (qw.size() == 1 && !numeric(qw[0].text)) {
                        put(d, 2, 2);
                        continue;
                    }
                    if (joined(d) == compactQuery) {
                        put(d, 0, 0);
                        continue;
                    }
                    if (ordered(qw, doc(d), false, letterX[documents[d].game])) {
                        const int kind = starts(joined(d), compactQuery) ? 1 : 2;
                        put(d, kind, kind);
                        continue;
                    }
                    if (numerals && ordered(qw, doc(d), true, letterX[documents[d].game])) {
                        if (queryCanonical.empty())
                            queryCanonical = canonical(q);
                        put(d, 5, queryCanonical == canonical(doc(d)) ? 0 : 2);
                        continue;
                    }
                    if (qw.size() > 1) {
                        size_t compatible {0};
                        const auto value = doc(d);
                        for (size_t at {0}; at < value.size();) {
                            const size_t end = std::min(value.find(' ', at), value.size());
                            const auto target = value.substr(at, end - at);
                            if (std::any_of(qw.begin(), qw.end(),
                                            [&](const Word& w) {
                                                return starts(target, w.text) ||
                                                       (LibrarySearch::numeric(w.text) &&
                                                        number(std::string(target)) ==
                                                            number(w.text));
                                            }) &&
                                ++compatible >= qw.size())
                                break;
                            at = end + 1;
                        }
                        if (compatible < qw.size())
                            continue;
                    }
                    const auto t = textFor(d);
                    if (wordMatch(qw, t, 1, nullptr))
                        put(d, 3, 3);
                    else if (wordMatch(qw, t, 2, nullptr))
                        put(d, 5, 3);
                }
            }
            if (matches.size() < limit || complete) {
                std::vector<Id> abbreviated;
                for (const auto& w : qw)
                    if (w.text.size() >= 2 && !numeric(w.text))
                        initials.append(gram(w.text, 0, std::min(size_t {3}, w.text.size())),
                                        abbreviated);
                unique(abbreviated);
                for (Id d : expand(abbreviated)) {
                    if (!allowed(documents[d].game))
                        continue;
                    const auto t = textFor(d);
                    if (rank(q, qw, t, nullptr, 4) == 4)
                        put(d, 4, 4);
                }
            }
            if (matches.size() < limit || complete) {
                std::vector<Id> docs;
                const bool shortMembership = substringMembership && qw.size() == 1 && q.size() < 3;
                if (shortMembership) {
                    docs.resize(documents.size());
                    std::iota(docs.begin(), docs.end(), 0);
                }
                else
                    docs = candidates(qw);
                std::vector<Id> ranked;
                Id last {UINT32_MAX};
                for (Id d : docs) {
                    const Id g = documents[d].game;
                    if (g == last)
                        continue;
                    last = g;
                    const auto previous = find(g);
                    if (allowed(g) && (!previous || previous->priority > 4))
                        ranked.push_back(g);
                }
                auto laterGame = [&](Id a, Id b) { return better(b, a); };
                if (!complete)
                    std::make_heap(ranked.begin(), ranked.end(), laterGame);
                const bool fuzzy = std::any_of(qw.begin(), qw.end(), [](const Word& w) {
                    return !digits(w.text) && codepoints(w.text).size() >= 5;
                });
                size_t strong = matches.size(), next {0};
                while (complete ? next < ranked.size() : (!ranked.empty() && strong < limit)) {
                    Id g;
                    if (complete)
                        g = ranked[next++];
                    else {
                        std::pop_heap(ranked.begin(), ranked.end(), laterGame);
                        g = ranked.back();
                        ranked.pop_back();
                    }
                    int best {9};
                    Id bestDoc {0};
                    const auto& fields = gameDocuments[g];
                    for (size_t n {0}; n < fields.size(); ++n) {
                        const Id d = fields[n];
                        if ((n && d == fields[0]) || (n == 2 && d == fields[1]))
                            continue;
                        if (substringMembership && containsCompact(doc(d), compactQuery)) {
                            best = 6;
                            bestDoc = d;
                            break;
                        }
                        if (complete && qw.size() == 1 && !fuzzy &&
                            LibrarySearch::numeric(qw[0].text)) {
                            const auto value = doc(d);
                            bool compatible {false};
                            if (joined(d).find(compactQuery) != std::string_view::npos) {
                                const auto wanted = number(qw[0].text);
                                for (size_t at {0}; at < value.size() && !compatible;) {
                                    const size_t end = std::min(value.find(' ', at), value.size());
                                    const auto token = value.substr(at, end - at);
                                    compatible = (token.size() <= 5 &&
                                                  number(std::string(token)) == wanted) ||
                                                 (digits(qw[0].text) && starts(token, qw[0].text));
                                    at = end + 1;
                                }
                            }
                            if (compatible) {
                                best = 6;
                                bestDoc = d;
                                break;
                            }
                            continue;
                        }
                        if (shortMembership)
                            continue;
                        const auto t = textFor(d);
                        const int r = rank(q, qw, t, nullptr, 6) == 6 ? 6 :
                                      fuzzy                           ? rank(q, qw, t, nullptr, 7) :
                                                                        -1;
                        if (r >= 0 && r < best) {
                            best = r;
                            bestDoc = d;
                        }
                        if (best == 6)
                            break;
                    }
                    if (best < 9) {
                        put(bestDoc, best, best);
                        if (best == 6)
                            ++strong;
                    }
                }
                if (metadata && (matches.size() < limit || complete)) {
                    std::vector<Id> groups;
                    size_t smallest = SIZE_MAX;
                    for (const auto& w : qw) {
                        std::vector<Id> found;
                        size_t count {0};
                        for (auto kind : {SuggestionKind::Developer, SuggestionKind::Publisher,
                                          SuggestionKind::Genre, SuggestionKind::System})
                            for (Id c : completionOrder[static_cast<size_t>(kind)])
                                if (entityMatches(c, w.text)) {
                                    found.push_back(c);
                                    count += completions[c].games.count;
                                }
                        if (found.empty()) {
                            groups.clear();
                            break;
                        }
                        if (count < smallest) {
                            smallest = count;
                            groups = std::move(found);
                        }
                    }
                    auto matchesMetadata = [&](Id g) {
                        return std::all_of(qw.begin(), qw.end(), [&](const Word& w) {
                            return std::any_of(
                                gameEntities[g].begin(), gameEntities[g].end(), [&](Id entity) {
                                    if (entity == UINT32_MAX)
                                        return false;
                                    const auto& field = entities[entity];
                                    if (field.compact.find(w.text) != std::string::npos)
                                        return true;
                                    return field.kind == SuggestionKind::System &&
                                           compact(fold(view(games[g].system, rawText)).text)
                                                   .find(w.text) != std::string::npos;
                                });
                        });
                    };
                    if (complete) {
                        // Counts need every member, without the ranked heap used by
                        // the top-results API. Reuse stamps to visit a candidate once.
                        if (scratch.metadataStamp.size() < games.size())
                            scratch.metadataStamp.resize(games.size());
                        for (Id c : groups) {
                            const auto range = completions[c].games;
                            for (Id at = range.begin; at < range.begin + range.count; ++at) {
                                const Id g = support[at];
                                if (scratch.metadataStamp[g] == scratch.epoch)
                                    continue;
                                scratch.metadataStamp[g] = scratch.epoch;
                                if (allowed(g) && !find(g) && matchesMetadata(g))
                                    put(gameDocuments[g][0], 8, 8);
                            }
                        }
                    }
                    else {
                        struct Cursor {
                            Id at, end;
                        };
                        auto later = [&](const Cursor& a, const Cursor& b) {
                            return rankingPosition[support[a.at]] > rankingPosition[support[b.at]];
                        };
                        std::priority_queue<Cursor, std::vector<Cursor>, decltype(later)> heap {
                            later};
                        for (Id c : groups) {
                            const auto range = completions[c].games;
                            if (range.count)
                                heap.push({range.begin, range.begin + range.count});
                        }
                        std::unordered_set<Id> checked;
                        while (!heap.empty() && matches.size() < limit) {
                            auto cursor = heap.top();
                            heap.pop();
                            const Id g = support[cursor.at++];
                            if (cursor.at < cursor.end)
                                heap.push(cursor);
                            if (!checked.insert(g).second || !allowed(g) || find(g))
                                continue;
                            if (matchesMetadata(g))
                                put(gameDocuments[g][0], 8, 8);
                        }
                    }
                }
            }
            auto& result = matches;
            auto less = [&](const Result& a, const Result& b) {
                return a.priority != b.priority ? a.priority < b.priority : better(a.game, b.game);
            };
            const size_t count = std::min(limit, result.size());
            if (!complete)
                std::partial_sort(result.begin(), result.begin() + count, result.end(), less);
            return {result.begin(), complete ? result.end() : result.begin() + count};
        }
    };

    Core::Core()
        : mIndex {std::make_unique<Index>()}
    {
    }
    Core::~Core() = default;
    Core::Core(Core&&) noexcept = default;
    Core& Core::operator=(Core&&) noexcept = default;
    Game Core::game(size_t index) const
    {
        if (index >= size())
            throw std::out_of_range("search game index");
        const auto g = mIndex->get(index);
        return {std::string(g.id),
                std::string(g.title),
                std::string(g.sortName),
                std::string(g.fileStem),
                std::string(g.developer),
                std::string(g.publisher),
                std::string(g.genre),
                std::string(g.system),
                std::string(g.systemName),
                Index::dateText(g.lastPlayed),
                g.playCount,
                g.favourite,
                g.hidden,
                g.kid,
                g.countAsGame,
                g.collection};
    }
    size_t Core::size() const { return mIndex->games.size(); }
    uint64_t Core::version() const { return mVersion; }
    void Core::clear()
    {
        mIndex = std::make_unique<Index>();
        mVersion = nextVersion.fetch_add(1, std::memory_order_relaxed);
    }

    void Core::rebuild(std::vector<Game> games)
    {
        clear(); // Release the old corpus before allocating a replacement index.
        auto& ix = *mIndex;
#ifdef SEARCH_TEST_BUILD_TIMING
        // Benchmark-only diagnostics, absent from the application build.
        const bool timing = std::getenv("SEARCH_BUILD_PROFILE") != nullptr;
        auto checkpoint = std::chrono::steady_clock::now();
        auto phase = [&](const char* name) {
            if (!timing)
                return;
            const auto now = std::chrono::steady_clock::now();
            std::printf("BUILD phase=%s ms=%.3f\n", name,
                        std::chrono::duration<double, std::milli>(now - checkpoint).count());
            checkpoint = now;
        };
#else
        auto phase = [](const char*) {};
#endif
        std::unordered_set<std::string> identities;
        games.erase(std::remove_if(games.begin(), games.end(),
                                   [&](Game& g) {
                                       if (!g.countAsGame || g.collection ||
                                           !identities.insert(g.id).second)
                                           return true;
                                       if (!validDate(g.lastPlayed))
                                           g.lastPlayed = "0";
                                       g.playCount = std::max(0, g.playCount);
                                       if (g.systemName.empty())
                                           g.systemName = g.system;
                                       return false;
                                   }),
                    games.end());
        identities.clear();
        identities.rehash(0);
        ix.games.reserve(games.size());
        // Intern raw fields once; views use arena offsets so arena growth is safe.
        std::unordered_map<std::string, Index::Ref> strings;
        size_t rawBytes {0};
        for (const auto& g : games)
            rawBytes += g.id.size() + g.title.size() + g.fileStem.size();
        ix.rawText.reserve(rawBytes);
        auto intern = [&](const std::string& value) {
            auto found = strings.find(value);
            if (found != strings.end())
                return found->second;
            const auto ref = Index::append(ix.rawText, value);
            strings.emplace(value, ref);
            return ref;
        };
        for (auto& g : games) {
            const auto id = Index::append(ix.rawText, g.id);
            const auto display = Index::append(ix.rawText, g.title);
            const auto sort = g.sortName == g.title ? display : intern(g.sortName);
            const auto file = g.fileStem == g.title    ? display :
                              g.fileStem == g.sortName ? sort :
                                                         Index::append(ix.rawText, g.fileStem);
            ix.games.push_back(
                {id, display, sort, file, intern(g.developer), intern(g.publisher), intern(g.genre),
                 intern(g.system), intern(g.systemName), Index::date(g.lastPlayed), g.playCount,
                 static_cast<uint32_t>(
                     std::count_if(g.title.begin(), g.title.end(),
                                   [](unsigned char c) { return (c & 0xc0) != 0x80; })),
                 g.favourite, g.hidden, g.kid, g.countAsGame, g.collection});
            g = {};
        }
        games.clear();
        games.shrink_to_fit();
        strings.clear();
        strings.rehash(0);
        ix.rawText.shrink_to_fit();

        identities.clear();
        identities.rehash(0);
        phase("records");
        ix.recent.resize(ix.games.size());
        ix.letterX.resize(ix.games.size());
        // X in the named Mega Man X series is a letter. Other X numerals
        // retain their usual value, even when an attached X2 title is present.
        for (uint32_t i {0}; i < ix.games.size(); ++i)
            if (const auto g = ix.get(i); g.lastPlayed != 0)
                ix.played.emplace(g.lastPlayed, i);
        size_t recent {0};
        for (auto it = ix.played.rbegin(); it != ix.played.rend() && recent++ < 30; ++it)
            ix.recent[it->second] = 1;
        using Id = Index::Id;
        struct WordHash {
            const std::string* pool;
            size_t operator()(Index::Ref r) const
            {
                return std::hash<std::string_view> {}({pool->data() + r.begin, r.size});
            }
        };
        struct WordEqual {
            const std::string* pool;
            bool operator()(Index::Ref a, Index::Ref b) const
            {
                return std::string_view(pool->data() + a.begin, a.size) ==
                       std::string_view(pool->data() + b.begin, b.size);
            }
        };
        std::unordered_map<Index::Ref, Id, WordHash, WordEqual> wordIds {0, WordHash {&ix.wordText},
                                                                         WordEqual {&ix.wordText}};
        wordIds.reserve(ix.games.size() * 2);
        ix.vocabulary.reserve(ix.games.size() * 2);
        ix.wordText.reserve(ix.games.size() * 12);
        std::vector<uint64_t> wordPairs, gramPairs, boundaryPairs, initialPairs;
        wordPairs.reserve(ix.games.size() * 6);
        initialPairs.reserve(ix.games.size() * 14);
        boundaryPairs.reserve(ix.games.size() * 10);
        std::map<std::pair<SuggestionKind, std::string>, std::vector<Id>> other;
        std::vector<Id> titles;
        titles.reserve(ix.games.size());
        std::vector<std::vector<Id>> displayWords;
        ix.gameDocuments.reserve(ix.games.size());
        ix.gameEntities.resize(ix.games.size(), {UINT32_MAX, UINT32_MAX, UINT32_MAX, UINT32_MAX});
        size_t textBytes {0};
        for (uint32_t n {0}; n < ix.games.size(); ++n) {
            const auto g = ix.get(n);
            textBytes += g.title.size();
            if (!g.sortName.empty() && g.sortName != g.title)
                textBytes += g.sortName.size();
            if (!g.fileStem.empty() && g.fileStem != g.title && g.fileStem != g.sortName)
                textBytes += g.fileStem.size();
        }
        ix.text.reserve(textBytes);
        ix.compactText.reserve(textBytes);
        ix.documents.reserve(ix.games.size() * 2);
        Id displayDocument {0}, postingDocument {0};
        std::vector<Id> lastWordGame, emittedBoundary, emittedInitial;
        auto emit = [&](std::vector<Id>& keys, std::vector<Id>& emitted,
                        std::vector<uint64_t>& pairs) {
            Index::unique(keys);
            for (Id key : keys)
                if (!std::binary_search(emitted.begin(), emitted.end(), key))
                    pairs.push_back(uint64_t {key} << 32 | postingDocument);
            emitted.insert(emitted.end(), keys.begin(), keys.end());
            Index::unique(emitted);
        };
        auto document = [&](std::string_view raw, Id g, bool display) {
            const Id d = ix.documents.size();
            const auto original = ix.get(g).title;
            std::string text;
            size_t sharedPrefix {0};
            if (!display && !original.empty() && starts(raw, original)) {
                sharedPrefix = ix.doc(displayDocument).size();
                text = ix.doc(displayDocument);
                const auto suffix = fold(raw.substr(original.size())).text;
                if (!suffix.empty()) {
                    text += ' ';
                    text += suffix;
                }
            }
            else {
                auto normalized = title(raw);
                if (display) {
                    ix.games[g].article = normalized.article;
                    constexpr std::string_view brand {"mega man x"};
                    ix.letterX[g] =
                        starts(normalized.text, brand) && (normalized.text.size() == brand.size() ||
                                                           normalized.text[brand.size()] == ' ' ||
                                                           (normalized.text[brand.size()] >= '0' &&
                                                            normalized.text[brand.size()] <= '9'));
                }
                text = std::move(normalized.text);
            }
            const auto joined = compact(text);
            ix.documents.push_back(
                {Index::append(ix.text, text), Index::append(ix.compactText, joined), g});
            const auto tokens = wordViews(text);
            std::vector<Id> uniqueWords;
            for (const auto& w : tokens) {
                if (w.offset < sharedPrefix)
                    continue; // Already indexed by this game's display title.
                const auto ref = Index::append(ix.wordText, w.text);
                auto inserted = wordIds.try_emplace(ref, ix.vocabulary.size());
                if (!inserted.second)
                    ix.wordText.resize(ref.begin);
                const Id id = inserted.first->second;
                if (inserted.second) {
                    const bool ascii = std::all_of(w.text.begin(), w.text.end(),
                                                   [](unsigned char c) { return c < 128; });
                    const auto points = ascii ? std::u32string {} : codepoints(w.text);
                    ix.vocabulary.push_back({ref,
                                             ascii ? signature(w.text) : signature(points),
                                             {},
                                             static_cast<Id>(ascii ? w.text.size() : points.size()),
                                             UINT32_MAX});
                    lastWordGame.push_back(UINT32_MAX);
                }
                if (lastWordGame[id] != g) {
                    wordPairs.push_back(uint64_t {id} << 32 | postingDocument);
                    lastWordGame[id] = g;
                }
                if (display) {
                    if (ix.vocabulary[id].completion == UINT32_MAX) {
                        ix.vocabulary[id].completion = displayWords.size();
                        displayWords.emplace_back();
                    }
                    uniqueWords.push_back(id);
                }
            }
            Index::unique(uniqueWords);
            for (Id w : uniqueWords)
                displayWords[ix.vocabulary[w].completion].push_back(g);
            std::vector<Id> boundaryKeys;
            for (size_t p {0}, count {0}; p < text.size(); ++p) {
                if (text[p] == ' ') {
                    if (count && count + 1 < joined.size())
                        boundaryKeys.push_back(gram(joined, count - 1, 3));
                    if (count >= 2 && count < joined.size())
                        boundaryKeys.push_back(gram(joined, count - 2, 3));
                }
                else
                    ++count;
            }
            emit(boundaryKeys, emittedBoundary, boundaryPairs);
            std::vector<uint32_t> initialKeys;
            const bool ordinary = std::all_of(tokens.begin(), tokens.end(), [](const WordView& w) {
                return !small(w.text) && !numeric(w.text) &&
                       static_cast<unsigned char>(w.text[0]) < 128;
            });
            if (ordinary) {
                for (size_t p {0}; p + 1 < tokens.size(); ++p) {
                    std::string initials;
                    initials += tokens[p].text[0];
                    initials += tokens[p + 1].text[0];
                    initialKeys.push_back(gram(initials, 0, 2));
                    if (p + 2 < tokens.size()) {
                        initials += tokens[p + 2].text[0];
                        initialKeys.push_back(gram(initials, 0, 3));
                    }
                }
            }
            else {
                std::vector<uint32_t> next {0}, current;
                next.reserve(16);
                current.reserve(16);
                size_t firstInitial {0};
                if (!display && !original.empty() && starts(raw, original)) {
                    const size_t prefixLength = ix.doc(displayDocument).size();
                    size_t significant {0};
                    for (size_t p {tokens.size()}; p-- > 0;) {
                        if (tokens[p].offset >= prefixLength)
                            continue;
                        if (!small(tokens[p].text) && ++significant == 2) {
                            firstInitial = p;
                            break;
                        }
                    }
                }
                for (size_t p {tokens.size()}; p-- > firstInitial;) {
                    current.clear();
                    current.push_back(0);
                    auto combine = [&](std::string_view choice) {
                        const size_t length = std::min(size_t {3}, choice.size());
                        const uint32_t code = gram(choice, 0, length) & 0xffffff;
                        for (auto suffix : next) {
                            const auto count = std::min(size_t {3}, length + (suffix >> 24));
                            const uint32_t joined =
                                length == 3 ? code : code | ((suffix & 0xffffff) << (8 * length));
                            current.push_back(static_cast<uint32_t>(count << 24) |
                                              (joined & 0xffffff));
                        }
                    };
                    const auto& word = tokens[p].text;
                    if (!numeric(word) && !digits(word)) {
                        const auto first = initial(word);
                        combine(first);
                    }
                    else if (word == "x" && ix.letterX[g])
                        combine("x");
                    else
                        for (const auto& choice : letters(word))
                            combine(choice);
                    if (small(word))
                        current.insert(current.end(), next.begin(), next.end());
                    std::sort(current.begin(), current.end());
                    current.erase(std::unique(current.begin(), current.end()), current.end());
                    for (auto key : current)
                        if ((key >> 24) >= 2)
                            initialKeys.push_back(key);
                    next.swap(current);
                }
            }
            emit(initialKeys, emittedInitial, initialPairs);
            return d;
        };
        std::unordered_map<std::string_view, std::vector<Id>*> metadataSupport[4];
        std::unordered_set<std::string_view> knownSystems;
        for (Id g {0}; g < ix.games.size(); ++g) {
            const auto game = ix.get(g);
            postingDocument = ix.documents.size();
            emittedBoundary.clear();
            emittedInitial.clear();
            const Id display = document(game.title, g, true);
            displayDocument = display;
            const Id sort = game.sortName.empty() || game.sortName == game.title ?
                                display :
                                document(game.sortName, g, false);
            const auto stem = withoutFileTags(game.fileStem);
            const Id file = stem.empty() || stem == game.title || stem == game.sortName ?
                                (stem == game.sortName ? sort : display) :
                                document(stem, g, false);
            ix.gameDocuments.push_back({display, sort, file});
            titles.push_back(g);
            for (const auto& field : {std::make_pair(SuggestionKind::Developer, &game.developer),
                                      {SuggestionKind::Publisher, &game.publisher},
                                      {SuggestionKind::Genre, &game.genre}}) {
                auto& cached = metadataSupport[static_cast<size_t>(field.first) -
                                               static_cast<size_t>(SuggestionKind::Developer)];
                auto found = cached.find(*field.second);
                if (found == cached.end()) {
                    const auto key = compact(fold(*field.second).text);
                    found = cached
                                .emplace(*field.second,
                                         key.empty() ? nullptr : &other[{field.first, key}])
                                .first;
                }
                if (found->second)
                    found->second->push_back(g);
            }
            auto found = metadataSupport[3].find(game.systemName);
            if (found == metadataSupport[3].end())
                found = metadataSupport[3]
                            .emplace(game.systemName,
                                     &other[{SuggestionKind::System, fold(game.systemName).text}])
                            .first;
            found->second->push_back(g);
            if (knownSystems.insert(game.system).second)
                for (const auto& alias : {fold(game.system).text, fold(game.systemName).text,
                                          title(game.systemName).text}) {
                    ix.systems[alias].insert(std::string(game.system));
                    ix.systems[compact(alias)].insert(std::string(game.system));
                }
        }
        phase("documents");
        // Flatten word/document lists: four-byte ids, no vector allocation per document.
        for (auto pair : wordPairs)
            ++ix.vocabulary[pair >> 32].documents.count;
        Id wordOffset {0};
        for (Id w {0}; w < ix.vocabulary.size(); ++w) {
            auto& range = ix.vocabulary[w].documents;
            range.begin = wordOffset;
            lastWordGame[w] = wordOffset;
            wordOffset += range.count;
        }
        ix.wordDocuments.resize(wordPairs.size());
        for (auto pair : wordPairs)
            ix.wordDocuments[lastWordGame[pair >> 32]++] = static_cast<Id>(pair);
        wordPairs.clear();
        wordPairs.shrink_to_fit();
        lastWordGame.clear();
        lastWordGame.shrink_to_fit();
        wordIds.clear();
        wordIds.rehash(0);
        // Finish and release the large document-pair buffers before building the
        // vocabulary grams; their temporary peaks must not overlap.
        ix.initials.build(std::move(initialPairs));
        ix.boundaries.build(std::move(boundaryPairs));
        for (Id w {0}; w < ix.vocabulary.size(); ++w) {
            const auto text = ix.word(w);
            for (size_t p {0}; p + 3 <= text.size(); ++p)
                gramPairs.push_back(uint64_t {gram(text, p, 3)} << 32 | w);
        }
        ix.wordGrams.build(std::move(gramPairs));
        for (Id w {0}; w < ix.vocabulary.size(); ++w) {
            const auto text = ix.word(w);
            if (std::all_of(text.begin(), text.end(), [](char c) { return c >= '0' && c <= '9'; }))
                continue;
            for (Id bit {0}; bit < 64; ++bit)
                if (ix.vocabulary[w].bits & (uint64_t {1} << bit))
                    ix.characterWords[bit].push_back(w);
        }
        for (auto& ids : ix.characterWords)
            ids.shrink_to_fit();

        phase("postings");
        auto completion = [&](SuggestionKind kind, Id key, std::vector<Id>& ids) {
            Index::unique(ids);
            const Id id = ix.completions.size();
            Index::Range range {static_cast<Id>(ix.support.size()), static_cast<Id>(ids.size())};
            uint32_t weight {0};
            for (Id g : ids)
                weight += ix.boost(g);
            ix.support.insert(ix.support.end(), ids.begin(), ids.end());
            ix.completions.push_back({kind, key, range, weight});
            ix.completionOrder[static_cast<size_t>(kind)].push_back(id);
            return id;
        };
        for (Id w {0}; w < ix.vocabulary.size(); ++w)
            if (ix.vocabulary[w].completion != UINT32_MAX)
                ix.vocabulary[w].completion =
                    completion(SuggestionKind::Word, w, displayWords[ix.vocabulary[w].completion]);
        displayWords.clear();
        displayWords.shrink_to_fit();
        auto titleKey = [&](Id g) { return ix.doc(ix.gameDocuments[g][0]); };
        Index::orderText(titles, titleKey);
        std::vector<Id> group;
        std::set<std::string> series;
        for (size_t i {0}; i < titles.size();) {
            const auto key = titleKey(titles[i]);
            size_t end = i + 1;
            while (end < titles.size() && titleKey(titles[end]) == key)
                ++end;
            group.assign(titles.begin() + i, titles.begin() + end);
            const Id c = completion(SuggestionKind::Title, ix.gameDocuments[titles[i]][0], group);
            uint8_t articles {0};
            for (Id g : group)
                if (ix.games[g].article)
                    articles |= 1 << (ix.games[g].article - 1);
            const std::array<const char*, 3> names {"the", "an", "a"};
            for (size_t n {0}; n < names.size(); ++n)
                if (articles & (1 << n))
                    ix.articles[names[n]].push_back(c);
            if (end < titles.size()) {
                const auto otherTitle = titleKey(titles[end]);
                size_t a {0}, b {0}, count {0};
                while (a < key.size() && b < otherTitle.size()) {
                    const size_t ae = std::min(key.find(' ', a), key.size());
                    const size_t be = std::min(otherTitle.find(' ', b), otherTitle.size());
                    const auto word = key.substr(a, ae - a);
                    const auto otherWord = otherTitle.substr(b, be - b);
                    if (word != otherWord) {
                        size_t common {0};
                        while (common < word.size() && common < otherWord.size() &&
                               word[common] == otherWord[common])
                            ++common;
                        while (common && word[common - 1] >= '0' && word[common - 1] <= '9')
                            --common;
                        const auto numericSuffix = [](std::string_view text) {
                            return std::all_of(text.begin(), text.end(),
                                               [](char c) { return c >= '0' && c <= '9'; });
                        };
                        if (count && common && !small(word.substr(0, common)) &&
                            numericSuffix(word.substr(common)) &&
                            numericSuffix(otherWord.substr(common)))
                            series.insert(std::string(key.substr(0, a + common)));
                        break;
                    }
                    if (++count >= 2 && !small(word))
                        series.insert(std::string(key.substr(0, ae)));
                    a = ae + 1;
                    b = be + 1;
                }
            }
            i = end;
        }
        for (const auto& s : series) {
            auto it =
                std::lower_bound(titles.begin(), titles.end(), s,
                                 [&](Id g, const std::string& key) { return titleKey(g) < key; });
            auto& ids = other[{SuggestionKind::Series, s}];
            for (; it != titles.end() && starts(titleKey(*it), s) &&
                   (titleKey(*it).size() == s.size() || titleKey(*it)[s.size()] == ' ' ||
                    (!(s.back() >= '0' && s.back() <= '9') && titleKey(*it)[s.size()] >= '0' &&
                     titleKey(*it)[s.size()] <= '9'));
                 ++it)
                ids.push_back(*it);
        }
        for (auto& pair : other) {
            if (pair.first.second.empty())
                continue;
            const Id entity = ix.entities.size();
            ix.entities.push_back(
                {pair.first.second, pair.first.first, compact(pair.first.second), {}});
            if (pair.first.first == SuggestionKind::System) {
                std::map<Id, Index::Ref> names;
                for (Id g : pair.second)
                    names.emplace(ix.games[g].system.begin, ix.games[g].system);
                for (const auto& name : names)
                    ix.entities.back().aliases.push_back(
                        compact(fold(ix.view(name.second, ix.rawText)).text));
            }
            if (pair.first.first != SuggestionKind::Series)
                for (Id g : pair.second)
                    ix.gameEntities[g][static_cast<size_t>(pair.first.first) -
                                       static_cast<size_t>(SuggestionKind::Developer)] = entity;
            completion(pair.first.first, entity, pair.second);
        }
        phase("completions");
        ix.wordOrder.resize(ix.vocabulary.size());
        std::iota(ix.wordOrder.begin(), ix.wordOrder.end(), 0);
        Index::orderText(ix.wordOrder, [&](Id id) { return ix.word(id); });
        ix.documentOrder.resize(ix.documents.size());
        std::iota(ix.documentOrder.begin(), ix.documentOrder.end(), 0);
        Index::orderText(ix.documentOrder, [&](Id id) { return ix.joined(id); });
        for (auto& order : ix.completionOrder)
            Index::orderText(order, [&](Id id) { return ix.key(id); });
        ix.rankingOrder.resize(ix.games.size());
        ix.rankingPosition.resize(ix.games.size());
        std::iota(ix.rankingOrder.begin(), ix.rankingOrder.end(), 0);
        std::sort(ix.rankingOrder.begin(), ix.rankingOrder.end(),
                  [&](Id a, Id b) { return ix.precedes(a, b); });
        for (Id n {0}; n < ix.rankingOrder.size(); ++n)
            ix.rankingPosition[ix.rankingOrder[n]] = n;
        for (const auto& c : ix.completions)
            std::sort(ix.support.begin() + c.games.begin,
                      ix.support.begin() + c.games.begin + c.games.count,
                      [&](Id a, Id b) { return ix.better(a, b); });
        phase("ordering");
        ix.vocabulary.shrink_to_fit();
        ix.wordText.shrink_to_fit();
        ix.support.shrink_to_fit();
        ix.completions.shrink_to_fit();
        ix.entities.shrink_to_fit();
        for (auto& order : ix.completionOrder)
            order.shrink_to_fit();
        mVersion = nextVersion.fetch_add(1, std::memory_order_relaxed);
    }

    std::vector<Match> Core::search(const std::string& query,
                                    size_t limit,
                                    const Filter& filter) const
    {
        return find(query, limit, filter, nullptr);
    }

    std::vector<Match> Core::find(const std::string& query,
                                  size_t limit,
                                  const Filter& inputFilter,
                                  Results* counts,
                                  size_t offset,
                                  const std::string& focusedGame) const
    {
        const auto filter = normalizedFilter(inputFilter);
        const auto& ix = *mIndex;
        const auto q = title(query).text;
        if (q.empty() || (!limit && !counts))
            return {};
        const auto qw = words(q);
        auto remaining = qw;
        std::set<std::string> systems;
        for (size_t pos {0}; pos < remaining.size();) {
            size_t consumed {0};
            for (size_t end = remaining.size(); end > pos; --end) {
                std::string alias;
                for (size_t w = pos; w < end; ++w) {
                    if (!alias.empty())
                        alias += ' ';
                    alias += remaining[w].text;
                }
                auto found = ix.systems.find(alias);
                if (found == ix.systems.end())
                    found = ix.systems.find(compact(alias));
                if (found != ix.systems.end()) {
                    systems.insert(found->second.begin(), found->second.end());
                    consumed = end - pos;
                    break;
                }
            }
            if (consumed)
                remaining.erase(remaining.begin() + pos, remaining.begin() + pos + consumed);
            else
                ++pos;
        }
        std::vector<Index::Result> selected;
        if (!systems.empty() && !remaining.empty()) {
            std::string rest;
            for (const auto& w : remaining) {
                if (!rest.empty())
                    rest += ' ';
                rest += w.text;
            }
            selected = ix.collect(rest, std::max(size_t {1}, limit), filter, true, &systems,
                                  counts != nullptr);
        }
        auto full = ix.collect(q, std::max(size_t {1}, limit), filter, selected.empty(), nullptr,
                               counts != nullptr);
        std::vector<Index::Result> rows;
        if (selected.empty())
            rows = std::move(full);
        else {
            std::unordered_map<uint32_t, Index::Result> merged;
            for (const auto& group : {&selected, &full})
                for (const auto& r : *group) {
                    auto it = merged.find(r.game);
                    if (it == merged.end() || r.priority < it->second.priority)
                        merged[r.game] = r;
                }
            for (const auto& item : merged)
                rows.push_back(item.second);
        }
        if (counts) {
            counts->total = rows.size();
            std::map<std::string_view, SystemCount> systems;
            for (const auto& row : rows) {
                const auto& game = ix.games[row.game];
                const auto system = ix.view(game.system, ix.rawText);
                auto& count = systems[system];
                if (!count.count) {
                    count.system = system;
                    count.name = ix.view(game.systemName, ix.rawText);
                }
                ++count.count;
            }
            for (auto& system : systems)
                counts->systems.push_back(std::move(system.second));
        }
        auto less = [&](const auto& a, const auto& b) {
            return a.priority != b.priority ? a.priority < b.priority : ix.better(a.game, b.game);
        };
        if (counts && !focusedGame.empty()) {
            const auto focused = std::find_if(rows.begin(), rows.end(), [&](const auto& row) {
                return ix.view(ix.games[row.game].id, ix.rawText) == focusedGame;
            });
            if (focused == rows.end())
                offset = 0;
            else {
                const size_t rank = std::count_if(
                    rows.begin(), rows.end(), [&](const auto& row) { return less(row, *focused); });
                if (rank < offset || rank >= offset + limit)
                    offset = limit ? rank / limit * limit : 0;
            }
        }
        offset = std::min(offset, rows.size());
        if (counts)
            counts->offset = offset;
        const size_t count = std::min(limit, rows.size() - offset);
        if (offset && offset < rows.size())
            std::nth_element(rows.begin(), rows.begin() + offset, rows.end(), less);
        std::partial_sort(rows.begin() + offset, rows.begin() + offset + count, rows.end(), less);
        rows.erase(rows.begin(), rows.begin() + offset);
        rows.resize(count);
        std::vector<Match> result;
        for (const auto& r : rows) {
            std::vector<Span> spans;
            if (r.kind < 8) {
                const auto mapped = title(ix.get(r.game).title, true);
                auto t = makeText(mapped.text);
                t.literalX = ix.letterX[r.game];
                std::string highlightQuery = q;
                auto highlightWords = qw;
                if (!systems.empty() && !remaining.empty() &&
                    systems.count(std::string(ix.get(r.game).system))) {
                    highlightQuery.clear();
                    for (auto w : remaining) {
                        if (!highlightQuery.empty())
                            highlightQuery += ' ';
                        highlightQuery += w.text;
                    }
                    highlightWords = words(highlightQuery);
                }
                rank(highlightQuery, highlightWords, t, &spans, r.kind);
                if (spans.empty())
                    rank(highlightQuery, highlightWords, t, &spans);
                for (auto& s : spans)
                    if (s.begin < s.end && s.end <= mapped.source.size())
                        s = {mapped.source[s.begin].begin, mapped.source[s.end - 1].end};
                mergeSpans(spans);
            }
            result.push_back({r.game, static_cast<MatchClass>(r.kind), std::move(spans)});
        }
        return result;
    }

    Results Core::query(const std::string& query,
                        size_t limit,
                        const Filter& inputFilter,
                        size_t offset,
                        const std::string& focusedGame) const
    {
        Results result;
        if (!title(query).text.empty()) {
            result.matches = find(query, limit, inputFilter, &result, offset, focusedGame);
            return result;
        }
        const auto filter = normalizedFilter(inputFilter);
        const auto& ix = *mIndex;
        std::map<std::string_view, SystemCount> systems;
        size_t focusedRank {SIZE_MAX};
        for (auto id : ix.rankingOrder) {
            if (!ix.allowed(id, filter))
                continue;
            const auto& game = ix.games[id];
            if (!focusedGame.empty() && ix.view(game.id, ix.rawText) == focusedGame)
                focusedRank = result.total;
            ++result.total;
            const auto system = ix.view(game.system, ix.rawText);
            auto& count = systems[system];
            if (!count.count) {
                count.system = system;
                count.name = ix.view(game.systemName, ix.rawText);
            }
            ++count.count;
            if (result.matches.size() < limit)
                result.matches.push_back({id, MatchClass::Exact, {}});
        }
        if (!focusedGame.empty()) {
            if (focusedRank == SIZE_MAX)
                offset = 0;
            else if (focusedRank < offset || focusedRank >= offset + limit)
                offset = limit ? focusedRank / limit * limit : 0;
        }
        result.offset = std::min(offset, result.total);
        if (result.offset) {
            result.matches.clear();
            size_t rank {0};
            for (auto id : ix.rankingOrder) {
                if (!ix.allowed(id, filter))
                    continue;
                if (rank++ < result.offset)
                    continue;
                if (result.matches.size() == limit)
                    break;
                result.matches.push_back({id, MatchClass::Exact, {}});
            }
        }
        for (auto& system : systems)
            result.systems.push_back(std::move(system.second));
        return result;
    }

    std::vector<size_t> Core::browse(size_t limit, const Filter& inputFilter) const
    {
        const auto filter = normalizedFilter(inputFilter);
        std::vector<size_t> result;
        for (auto id : mIndex->rankingOrder) {
            if (result.size() == limit)
                break;
            if (mIndex->allowed(id, filter))
                result.push_back(id);
        }
        return result;
    }

    std::vector<Match> Core::closest(const std::string& query,
                                     size_t limit,
                                     const Filter& inputFilter) const
    {
        const auto q = codepoints(normalize(query));
        if (q.empty() || q.size() > 128 || !limit)
            return {};
        const auto filter = normalizedFilter(inputFilter);
        const auto& ix = *mIndex;
        // Recommendations are separate from real typo matches. Reuse interned title
        // views and cache word distances without allocating owning game records.
        std::unordered_map<std::string_view, size_t> distances, titles;
        std::unordered_map<char32_t, uint64_t> pattern;
        if (q.size() <= 64)
            for (size_t i {0}; i < q.size(); ++i)
                pattern[q[i]] |= uint64_t {1} << i;
        auto distance = [&](std::string_view text) {
            const auto cached = distances.find(text);
            if (cached != distances.end())
                return cached->second;
            const auto points = codepoints(std::string(text));
            if (q.size() <= 64) {
                // Bit-parallel Levenshtein keeps closest recommendations bounded for
                // varied libraries, including Unicode code points rather than UTF-8 bytes.
                uint64_t positive = UINT64_MAX, negative {0};
                size_t score = q.size();
                const uint64_t high = uint64_t {1} << (q.size() - 1);
                for (size_t i {0}; i < points.size() && i < 256; ++i) {
                    const auto mask = pattern.find(points[i]);
                    const uint64_t equal = mask == pattern.end() ? 0 : mask->second;
                    const uint64_t vertical = equal | negative;
                    const uint64_t horizontal =
                        (((equal & positive) + positive) ^ positive) | equal;
                    uint64_t plus = negative | ~(horizontal | positive);
                    uint64_t minus = positive & horizontal;
                    score += (plus & high) != 0;
                    score -= (minus & high) != 0;
                    plus = (plus << 1) | 1;
                    minus <<= 1;
                    positive = minus | ~(vertical | plus);
                    negative = plus & vertical;
                }
                distances.emplace(text, score);
                return score;
            }
            std::vector<size_t> previous(q.size() + 1), current(q.size() + 1);
            std::iota(previous.begin(), previous.end(), 0);
            for (size_t i {0}; i < points.size() && i < 256; ++i) {
                current[0] = i + 1;
                for (size_t j {0}; j < q.size(); ++j)
                    current[j + 1] = std::min(
                        {current[j] + 1, previous[j + 1] + 1, previous[j] + (points[i] != q[j])});
                previous.swap(current);
            }
            distances.emplace(text, previous.back());
            return previous.back();
        };
        const bool phrase = normalize(query).find(' ') != std::string::npos;
        std::vector<std::pair<size_t, uint32_t>> nearest;
        for (uint32_t id {0}; id < ix.games.size(); ++id) {
            if (!ix.allowed(id, filter))
                continue;
            const auto text = ix.doc(ix.gameDocuments[id][0]);
            auto found = titles.find(text);
            if (found == titles.end()) {
                size_t score = phrase ? distance(text) : q.size() + 256;
                // Word views point into the immutable title arena, not temporary tokens.
                for (size_t begin {0}; begin < text.size();) {
                    auto end = text.find(' ', begin);
                    if (end == std::string_view::npos)
                        end = text.size();
                    if (end > begin)
                        score = std::min(score, distance(text.substr(begin, end - begin)));
                    begin = end + 1;
                }
                found = titles.emplace(text, score).first;
            }
            nearest.emplace_back(found->second, id);
        }
        const auto retained = std::min(limit, nearest.size());
        std::partial_sort(nearest.begin(), nearest.begin() + retained, nearest.end());
        std::vector<Match> result;
        for (size_t i {0}; i < retained; ++i)
            result.push_back({nearest[i].second, MatchClass::Typo, {}});
        return result;
    }

    std::vector<Suggestion> Core::suggest(const std::string& query,
                                          size_t limit,
                                          const Filter& inputFilter) const
    {
        const auto filter = normalizedFilter(inputFilter);
        const auto& ix = *mIndex;
        const auto q = normalize(query);
        if (!limit)
            return {};
        if (q.empty()) {
            std::vector<uint32_t> candidates;
            for (uint32_t id {0}; id < ix.completions.size(); ++id) {
                const auto kind = ix.completions[id].kind;
                if (kind != SuggestionKind::Title && kind != SuggestionKind::Word)
                    candidates.push_back(id);
            }
            std::sort(candidates.begin(), candidates.end(), [&](uint32_t a, uint32_t b) {
                const auto& x = ix.completions[a];
                const auto& y = ix.completions[b];
                return x.weight != y.weight ? x.weight > y.weight : a < b;
            });
            std::vector<Suggestion> result;
            std::set<std::string> seen;
            for (auto id : candidates) {
                const auto& c = ix.completions[id];
                std::string display;
                if (ix.key(id) == "unknown")
                    continue;
                for (uint32_t n {0}; n < c.games.count; ++n) {
                    const auto g = ix.support[c.games.begin + n];
                    if (!ix.allowed(g, filter))
                        continue;
                    const auto game = ix.get(g);
                    if (c.kind == SuggestionKind::Developer)
                        display = game.developer;
                    else if (c.kind == SuggestionKind::Publisher)
                        display = game.publisher;
                    else if (c.kind == SuggestionKind::Genre)
                        display = game.genre;
                    else if (c.kind == SuggestionKind::System)
                        display = game.systemName;
                    else {
                        const auto mapped = title(game.title, true);
                        const size_t length = ix.entities[c.key].key.size();
                        if (!length || length > mapped.source.size())
                            continue;
                        display = game.title.substr(mapped.source.front().begin,
                                                    mapped.source[length - 1].end -
                                                        mapped.source.front().begin);
                    }
                    break;
                }
                if (display.empty() || !seen.insert(normalize(display)).second)
                    continue;
                result.push_back({c.kind, std::move(display)});
                if (result.size() == limit)
                    break;
            }
            return result;
        }
        const auto split = q.rfind(' ');
        const bool trailing = query.back() == ' ';
        const std::string before = trailing                   ? q + " " :
                                   split == std::string::npos ? "" :
                                                                q.substr(0, split + 1);
        const std::string partial = trailing                   ? "" :
                                    split == std::string::npos ? q :
                                                                 q.substr(split + 1);
        std::vector<uint32_t> candidates;
        for (size_t kind {0}; kind < ix.completionOrder.size(); ++kind) {
            const auto prefix =
                compact(kind == static_cast<size_t>(SuggestionKind::Word) ? partial :
                        kind == static_cast<size_t>(SuggestionKind::Title) ||
                                kind == static_cast<size_t>(SuggestionKind::Series) ?
                                                                            title(query).text :
                                                                            q);
            if (prefix.empty())
                continue;
            const auto& order = ix.completionOrder[kind];
            auto begin = std::lower_bound(
                order.begin(), order.end(), prefix,
                [&](uint32_t id, const std::string& text) { return ix.key(id) < text; });
            for (auto it = begin; it != order.end() && starts(ix.key(*it), prefix); ++it)
                candidates.push_back(*it);
        }
        for (uint32_t id : ix.completionOrder[static_cast<size_t>(SuggestionKind::System)]) {
            const auto& entity = ix.entities[ix.completions[id].key];
            if (std::any_of(entity.aliases.begin(), entity.aliases.end(),
                            [&](const std::string& alias) { return starts(alias, compact(q)); }))
                candidates.push_back(id);
        }
        for (const auto& article : ix.articles)
            if (starts(article.first, q))
                candidates.insert(candidates.end(), article.second.begin(), article.second.end());
        Index::unique(candidates);
        if (candidates.empty())
            return {};
        const bool shortQuery = codepoints(q).size() <= 2;
        const auto article = q == "the" ? ix.articles.find(q) : ix.articles.end();
        const uint8_t articleCode = q == "the" ? 1 : q == "an" ? 2 : q == "a" ? 3 : 0;
        auto articleTitle = [&](uint32_t id) {
            return article != ix.articles.end() &&
                   std::binary_search(article->second.begin(), article->second.end(), id);
        };
        auto preferredSuggestion = [&](uint32_t a, uint32_t b) {
            const auto& x = ix.completions[a];
            const auto& y = ix.completions[b];
            if (articleTitle(a) != articleTitle(b))
                return articleTitle(a);
            auto preferred = [](SuggestionKind k) {
                return k == SuggestionKind::Word || k == SuggestionKind::Title;
            };
            if (shortQuery && preferred(x.kind) != preferred(y.kind))
                return preferred(x.kind);
            if (x.weight != y.weight)
                return x.weight > y.weight;
            if (x.kind != y.kind)
                return (x.kind == SuggestionKind::Word ? 99 : static_cast<int>(x.kind)) <
                       (y.kind == SuggestionKind::Word ? 99 : static_cast<int>(y.kind));
            const int compared = ix.key(a).compare(ix.key(b));
            return compared ? compared < 0 : a < b;
        };
        auto later = [&](uint32_t a, uint32_t b) { return preferredSuggestion(b, a); };
        std::make_heap(candidates.begin(), candidates.end(), later);
        // Context uses word/document posting intersections once, never a library-sized
        // find() for each candidate suggestion. Insertions are checked only at their source.
        std::vector<uint32_t> context;
        auto contextTokens = words(title(query).text);
        if (!trailing && !contextTokens.empty())
            contextTokens.pop_back();
        const bool wordContext =
            !contextTokens.empty() &&
            std::any_of(candidates.begin(), candidates.end(), [&](uint32_t id) {
                return ix.completions[id].kind == SuggestionKind::Word;
            });
        if (wordContext) {
            auto docs = ix.prefixCandidates(contextTokens);
            if (docs.empty())
                docs = ix.candidates(contextTokens);
            for (auto d : docs)
                context.push_back(ix.documents[d].game);
            Index::unique(context);
        }
        std::vector<Suggestion> result;
        std::unordered_set<std::string> seen;
        while (!candidates.empty()) {
            std::pop_heap(candidates.begin(), candidates.end(), later);
            const auto id = candidates.back();
            candidates.pop_back();
            const auto& c = ix.completions[id];
            const auto insertionKey = c.kind == SuggestionKind::Word ?
                                          compact(before + std::string(ix.key(id))) :
                                          compact(std::string(ix.key(id)));
            if (insertionKey == compact(q))
                continue;
            if (c.kind == SuggestionKind::Word && wordContext && context.empty())
                continue;
            if (c.kind != SuggestionKind::Title && c.kind != SuggestionKind::Word &&
                c.kind != SuggestionKind::System && ix.key(id) == "unknown")
                continue;
            std::string insert;
            bool valid {false};
            for (uint32_t n {0}; n < c.games.count; ++n) {
                const auto g = ix.support[c.games.begin + n];
                if (!ix.allowed(g, filter) ||
                    (articleTitle(id) && ix.games[g].article != articleCode))
                    continue;
                const auto game = ix.get(g);
                if (c.kind == SuggestionKind::Word) {
                    if (!before.empty() && !std::binary_search(context.begin(), context.end(), g))
                        continue;
                    const auto mapped = title(game.title, true);
                    auto t = makeText(mapped.text);
                    t.literalX = ix.letterX[g];
                    const auto text = ix.word(c.key);
                    auto found = std::find_if(t.tokens.begin(), t.tokens.end(),
                                              [&](const auto& w) { return w.text == text; });
                    if (found == t.tokens.end())
                        continue;
                    insert =
                        before + std::string(game.title.substr(
                                     mapped.source[found->offset].begin,
                                     mapped.source[found->offset + found->text.size() - 1].end -
                                         mapped.source[found->offset].begin));
                    if (!before.empty()) {
                        const auto normalized = title(insert).text;
                        if (rank(normalized, words(normalized), t) < 0)
                            continue;
                    }
                }
                else if (c.kind == SuggestionKind::Title)
                    insert = game.title;
                else if (c.kind == SuggestionKind::Developer)
                    insert = game.developer;
                else if (c.kind == SuggestionKind::Publisher)
                    insert = game.publisher;
                else if (c.kind == SuggestionKind::Genre)
                    insert = game.genre;
                else if (c.kind == SuggestionKind::System)
                    insert = game.systemName;
                else {
                    const auto mapped = title(game.title, true);
                    const size_t length = ix.entities[c.key].key.size();
                    if (length > mapped.source.size() || !length)
                        continue;
                    insert = game.title.substr(mapped.source.front().begin,
                                               mapped.source[length - 1].end -
                                                   mapped.source.front().begin);
                }
                valid = true;
                break;
            }
            const auto key = compact(normalize(insert));
            if (!valid || key == compact(q) || !seen.insert(key).second)
                continue;
            result.push_back({c.kind, std::move(insert)});
            if (result.size() == limit)
                break;
        }
        return result;
    }

    std::vector<size_t> Core::recentlyPlayed(size_t limit, const Filter& inputFilter) const
    {
        const auto filter = normalizedFilter(inputFilter);
        std::vector<size_t> result;
        for (auto it = mIndex->played.rbegin();
             it != mIndex->played.rend() && result.size() < limit; ++it)
            if (mIndex->allowed(it->second, filter))
                result.push_back(it->second);
        return result;
    }

    void Core::update(size_t index, const Game& value)
    {
        auto& ix = *mIndex;
        auto& game = ix.games.at(index);
        const auto timestamp = Index::date(validDate(value.lastPlayed) ? value.lastPlayed : "0");
        if (game.favourite == value.favourite && game.lastPlayed == timestamp &&
            game.playCount == std::max(0, value.playCount)) {
            game.hidden = value.hidden;
            game.kid = value.kid;
            mVersion = nextVersion.fetch_add(1, std::memory_order_relaxed);
            return;
        }
        std::vector<uint32_t> changed {static_cast<uint32_t>(index)};
        std::unordered_map<uint32_t, uint32_t> oldBoost;
        // Only the former/new top thirty can change recent vocabulary boosts.
        std::vector<uint32_t> recent;
        for (auto it = ix.played.rbegin(); it != ix.played.rend() && recent.size() < 30; ++it)
            recent.push_back(it->second);
        for (auto g : recent)
            oldBoost[g] = ix.boost(g);
        oldBoost[index] = ix.boost(index);
        const auto oldPosition = ix.rankingPosition[index];
        ix.rankingOrder.erase(ix.rankingOrder.begin() + oldPosition);
        ix.played.erase({game.lastPlayed, static_cast<uint32_t>(index)});
        game.favourite = value.favourite;
        game.lastPlayed = timestamp;
        game.playCount = std::max(0, value.playCount);
        game.hidden = value.hidden;
        game.kid = value.kid;
        if (game.lastPlayed)
            ix.played.emplace(game.lastPlayed, index);
        for (auto g : recent)
            ix.recent[g] = 0;
        for (auto it = ix.played.rbegin(); it != ix.played.rend() && changed.size() < 31; ++it) {
            ix.recent[it->second] = 1;
            changed.push_back(it->second);
        }
        changed.insert(changed.end(), recent.begin(), recent.end());
        Index::unique(changed);
        auto position = std::lower_bound(ix.rankingOrder.begin(), ix.rankingOrder.end(), index,
                                         [&](uint32_t a, uint32_t b) { return ix.precedes(a, b); });
        const auto newPosition = static_cast<uint32_t>(position - ix.rankingOrder.begin());
        ix.rankingOrder.insert(position, index);
        for (uint32_t n = std::min(oldPosition, newPosition);
             n <= std::max(oldPosition, newPosition); ++n)
            ix.rankingPosition[ix.rankingOrder[n]] = n;
        for (auto g : changed) {
            const int difference =
                static_cast<int>(ix.boost(g)) -
                static_cast<int>(oldBoost[g] ? oldBoost[g] : 1 + (ix.games[g].favourite ? 4 : 0));
            if (!difference && g != index)
                continue;
            const auto titleText = title(ix.get(g).title).text;
            for (auto kind : {SuggestionKind::Title, SuggestionKind::Word, SuggestionKind::Series,
                              SuggestionKind::Developer, SuggestionKind::Publisher,
                              SuggestionKind::Genre, SuggestionKind::System}) {
                std::vector<std::string> keys;
                if (kind == SuggestionKind::Title)
                    keys.push_back(titleText);
                else if (kind == SuggestionKind::Word)
                    for (const auto& w : words(titleText))
                        keys.push_back(w.text);
                else if (kind == SuggestionKind::Series) {
                    const auto ws = words(titleText);
                    for (size_t n {2}; n <= ws.size(); ++n) {
                        keys.push_back(titleText.substr(0, n == ws.size() ? titleText.size() :
                                                                            ws[n].offset - 1));
                        const auto& word = ws[n - 1];
                        size_t base = word.text.size();
                        while (base && word.text[base - 1] >= '0' && word.text[base - 1] <= '9')
                            --base;
                        if (base && base < word.text.size())
                            keys.push_back(titleText.substr(0, word.offset + base));
                    }
                }
                else
                    keys.push_back(fold(kind == SuggestionKind::Developer ? ix.get(g).developer :
                                        kind == SuggestionKind::Publisher ? ix.get(g).publisher :
                                        kind == SuggestionKind::Genre     ? ix.get(g).genre :
                                                                            ix.get(g).systemName)
                                       .text);
                std::sort(keys.begin(), keys.end());
                keys.erase(std::unique(keys.begin(), keys.end()), keys.end());
                const auto& order = ix.completionOrder[static_cast<size_t>(kind)];
                for (const auto& key : keys) {
                    auto it = std::lower_bound(order.begin(), order.end(), key,
                                               [&](uint32_t c, const std::string& text) {
                                                   return Index::compare(ix.key(c), text) < 0;
                                               });
                    if (it != order.end() && Index::compare(ix.key(*it), key) == 0) {
                        auto& c = ix.completions[*it];
                        c.weight += difference;
                        if (g == index && oldPosition != newPosition) {
                            auto first = ix.support.begin() + c.games.begin;
                            auto last = first + c.games.count;
                            auto at = std::find(first, last, index);
                            if (at != last) {
                                // Removing one changed game preserves the order of every other
                                // source.
                                std::rotate(at, at + 1, last);
                                auto target = std::lower_bound(
                                    first, last - 1, index,
                                    [&](uint32_t a, uint32_t b) { return ix.better(a, b); });
                                std::rotate(target, last - 1, last);
                            }
                        }
                    }
                }
            }
        }
        mVersion = nextVersion.fetch_add(1, std::memory_order_relaxed);
    }
} // namespace LibrarySearch
