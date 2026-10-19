//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  SearchCore.cpp
//
//  Written for ES-DE-Plus. Immutable indexed library search and autocomplete.
//

#include "search/SearchCore.h"

#include <algorithm>
#include <array>
#include <functional>
#include <map>
#include <numeric>
#include <set>
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
        };

        Folded fold(const std::string& input, bool mapping = false)
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

        struct Word {
            std::string text;
            size_t offset;
        };
        std::vector<Word> words(const std::string& text)
        {
            std::vector<Word> result;
            for (size_t begin {0}; begin < text.size();) {
                size_t end {text.find(' ', begin)};
                if (end == std::string::npos)
                    end = text.size();
                result.push_back({text.substr(begin, end - begin), begin});
                begin = end + 1;
            }
            return result;
        }
        bool small(const std::string& word)
        {
            return word == "a" || word == "an" || word == "the" || word == "of" || word == "to" ||
                   word == "and";
        }
        Folded title(const std::string& text, bool mapping = false)
        {
            auto result = fold(text, mapping);
            size_t remove {0};
            for (const std::string article : {"the ", "an ", "a "})
                if (starts(result.text, article)) {
                    remove = article.size();
                    break;
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
        std::string number(const std::string& text)
        {
            if (text.empty() || text.size() > 5 ||
                (text[0] != 'i' && text[0] != 'v' && text[0] != 'x'))
                return text;
            for (size_t i {1}; i < romans.size(); ++i)
                if (text == romans[i])
                    return std::to_string(i);
            return text;
        }
        std::string initial(const std::string& word)
        {
            int32_t end {0};
            UChar32 cp;
            U8_NEXT(word.data(), end, static_cast<int32_t>(word.size()), cp);
            return word.substr(0, end);
        }
        std::vector<std::string> letters(const std::string& word)
        {
            const auto numeric {number(word)};
            if (numeric != word)
                return {initial(word), word, numeric};
            if (!word.empty() && std::all_of(word.begin(), word.end(),
                                             [](char c) { return c >= '0' && c <= '9'; })) {
                if (word.size() <= 2) {
                    const int value {word.size() == 1 ? word[0] - '0' :
                                                        (word[0] - '0') * 10 + word[1] - '0'};
                    if (value > 0 && value <= 20)
                        return {word, romans[value]};
                }
                return {initial(word), word};
            }
            return {initial(word)};
        }
        std::u32string codepoints(const std::string& text)
        {
            std::u32string result;
            for (int32_t i {0}; i < static_cast<int32_t>(text.size());) {
                UChar32 cp;
                U8_NEXT(text.data(), i, static_cast<int32_t>(text.size()), cp);
                result.push_back(cp);
            }
            return result;
        }
        uint64_t signature(const std::u32string& word)
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
        bool near(const std::u32string& a, const std::u32string& b)
        {
            const size_t threshold {a.size() >= 9 ? 2U : 1U};
            if (a.size() < 5 || a.size() > b.size() + threshold || b.size() > a.size() + threshold)
                return false;
            if (bitCount(signature(a) & ~signature(b)) > threshold)
                return false;
            // Banded optimal-string-alignment distance, including adjacent transpositions.
            std::vector<size_t> prev(b.size() + 1), row(b.size() + 1), before(b.size() + 1);
            std::iota(prev.begin(), prev.end(), 0);
            for (size_t i {1}; i <= a.size(); ++i) {
                std::fill(row.begin(), row.end(), threshold + 1);
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
                before.swap(prev);
                prev.swap(row);
            }
            return prev[b.size()] <= threshold;
        }
        bool visible(const Game& g, const Filter& f)
        {
            return g.countAsGame && !g.collection && (f.showHidden || !g.hidden) &&
                   (!f.kidMode || g.kid) && (!f.favouritesOnly || g.favourite) &&
                   (f.system.empty() || g.system == f.system) &&
                   (f.genre.empty() || g.genre == f.genre) &&
                   (f.developer.empty() || g.developer == f.developer) &&
                   (f.publisher.empty() || g.publisher == f.publisher);
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
        struct Text {
            std::string value;
            std::vector<Word> tokens;
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
                if (mode == 2)
                    return starts(number(t.tokens[w].text), number(query[q].text));
                if (mode == 3)
                    return starts(t.tokens[w].text, query[q].text) ||
                           near(codepoints(query[q].text), codepoints(t.tokens[w].text));
                return starts(t.tokens[w].text, query[q].text);
            };
            std::vector<int> owner(t.tokens.size(), -1);
            if (mode == 0) {
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
            const auto& ws {title.tokens};
            // DP state (word, query byte) bounds work even with many optional small words.
            for (size_t start {0}; start < ws.size(); ++start) {
                std::set<std::pair<size_t, size_t>> failed;
                std::vector<Span> path;
                std::function<bool(size_t, size_t, size_t)> visit = [&](size_t w, size_t p,
                                                                        size_t used) {
                    if (p == query.size())
                        return used >= 2;
                    if (w == ws.size() || failed.count({w, p}))
                        return false;
                    for (const auto& s : letters(ws[w].text)) {
                        if (query.compare(p, s.size(), s) != 0)
                            continue;
                        const auto length {s == initial(ws[w].text) ? s.size() : ws[w].text.size()};
                        path.push_back({ws[w].offset, ws[w].offset + length});
                        if (visit(w + 1, p + s.size(), used + 1))
                            return true;
                        path.pop_back();
                    }
                    if (small(ws[w].text) && visit(w + 1, p, used))
                        return true;
                    failed.insert({w, p});
                    return false;
                };
                if (visit(start, 0, 0)) {
                    if (spans)
                        spans->insert(spans->end(), path.begin(), path.end());
                    return true;
                }
            }
            return false;
        }
        int rank(const std::string& q,
                 const std::vector<Word>& qw,
                 const Text& t,
                 std::vector<Span>* spans = nullptr,
                 int wanted = -1)
        {
            const auto cq {compact(q)};
            const auto ct {compact(t.value)};
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
            if ((wanted < 0 || wanted == 1) && starts(ct, cq)) {
                compactSpan(0, cq.size());
                return 1;
            }
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
                        std::find_if(t.tokens.begin(), t.tokens.end(),
                                     [&](const Word& word) { return starts(word.text, w.text); });
                    if (pos != t.tokens.end())
                        abbreviated.push_back({pos->offset, pos->offset + w.text.size()});
                    else {
                        if (!acronym(w.text, t, &abbreviated)) {
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
            if ((wanted < 0 || wanted == 6) && pos != std::string::npos) {
                compactSpan(pos, pos + cq.size());
                return 6;
            }
            if ((wanted < 0 || wanted == 7) && wordMatch(qw, t, 3, spans))
                return 7;
            return -1;
        }
    } // namespace

    std::string normalize(const std::string& text) { return fold(text).text; }

    struct Core::Index {
        struct Vocabulary {
            std::string text;
            std::u32string points;
            std::vector<size_t> games;
        };
        struct Completion {
            SuggestionKind kind;
            std::string text;
            std::string key;
            std::vector<size_t> games;
            uint64_t weight {0};
        };
        struct Document {
            Text text;
            std::string compact;
            std::vector<size_t> games;
            std::string display;
            std::vector<size_t> displayGames;
        };
        std::vector<Game> games;
        std::vector<Document> documents;
        std::vector<std::array<size_t, 3>> gameDocuments;
        std::vector<size_t> sortedTitles;
        std::map<std::string, std::vector<size_t>> metadataGroups;
        std::map<std::string, Vocabulary> vocabulary;
        std::map<size_t, std::unordered_map<uint64_t, std::vector<const Vocabulary*>>> signatures;
        std::unordered_map<uint32_t, std::vector<size_t>> grams;
        std::unordered_map<std::string, std::vector<size_t>> acronymPrefixes;
        std::map<std::string, std::set<std::string>> systems;
        std::map<std::string, std::vector<size_t>> systemGames;
        std::vector<Completion> completions;
        std::array<std::vector<size_t>, 3> completionOrder;
        std::vector<size_t> recent;
    };

    Core::Core()
        : mIndex {std::make_unique<Index>()}
    {
    }
    Core::~Core() = default;
    Core::Core(Core&&) noexcept = default;
    Core& Core::operator=(Core&&) noexcept = default;
    const Game& Core::game(size_t index) const { return mIndex->games.at(index); }
    size_t Core::size() const { return mIndex->games.size(); }

    void Core::rebuild(std::vector<Game> games)
    {
        auto index = std::make_unique<Index>();
        // Sort once by tie breaks. Posting lists and bucket traversal retain this order.
        std::unordered_map<std::string, std::string> normalized;
        normalized.reserve(games.size() * 2);
        index->games.reserve(games.size());
        index->documents.reserve(games.size());
        auto cached = [&](const std::string& value) -> const std::string& {
            auto it = normalized.find(value);
            if (it == normalized.end())
                it = normalized.emplace(value, normalize(value)).first;
            return it->second;
        };
        std::vector<size_t> order(games.size());
        std::iota(order.begin(), order.end(), 0);
        std::vector<const std::string*> sortKeys, systemKeys;
        std::vector<size_t> lengths;
        for (auto& g : games) {
            sortKeys.push_back(&cached(g.sortName.empty() ? g.title : g.sortName));
            systemKeys.push_back(&cached(g.systemName));
            lengths.push_back(static_cast<size_t>(
                std::count_if(g.title.begin(), g.title.end(),
                              [](unsigned char c) { return (c & 0xc0) != 0x80; })));
            const auto& date = g.lastPlayed;
            if (date.size() != 15 || date[8] != 'T' ||
                !std::all_of(date.begin(), date.end(),
                             [](unsigned char c) { return (c >= '0' && c <= '9') || c == 'T'; }))
                g.lastPlayed = "0";
            if (g.playCount < 0)
                g.playCount = 0;
        }
        std::sort(order.begin(), order.end(), [&](size_t ai, size_t bi) {
            const auto& a = games[ai];
            const auto& b = games[bi];
            if (a.favourite != b.favourite)
                return a.favourite;
            if (a.lastPlayed != b.lastPlayed)
                return a.lastPlayed > b.lastPlayed;
            if (a.playCount != b.playCount)
                return a.playCount > b.playCount;
            if (lengths[ai] != lengths[bi])
                return lengths[ai] < lengths[bi];
            if (*sortKeys[ai] != *sortKeys[bi])
                return *sortKeys[ai] < *sortKeys[bi];
            if (*systemKeys[ai] != *systemKeys[bi])
                return *systemKeys[ai] < *systemKeys[bi];
            return a.id < b.id;
        });
        std::unordered_set<std::string> identities;
        identities.reserve(games.size());
        std::unordered_map<std::string, size_t> completionKeys;
        auto completion = [&](SuggestionKind kind, const std::string& text, const auto& ids,
                              const std::string& overrideKey = std::string {}) {
            const auto& key = overrideKey.empty() ? cached(text) : overrideKey;
            if (key.empty() || key == "unknown")
                return;
            const auto pair = std::string(1, static_cast<char>('0' + static_cast<int>(kind))) + key;
            auto it = completionKeys.find(pair);
            if (it == completionKeys.end()) {
                it = completionKeys.emplace(pair, index->completions.size()).first;
                index->completions.push_back({kind, text, key, {}, 0});
            }
            auto& c = index->completions[it->second];
            for (size_t i : ids) {
                c.games.push_back(i);
                const auto& g = index->games[i];
                c.weight += 1 + (g.favourite ? 4 : 0) + (g.lastPlayed > "19700101T000000" ? 2 : 0);
            }
        };
        std::unordered_map<std::string, size_t> rawTitles;
        rawTitles.reserve(games.size());
        auto addTitle = [&](const std::string& raw, size_t i) {
            auto found = rawTitles.find(raw);
            size_t id;
            if (found != rawTitles.end())
                id = found->second;
            else {
                auto value = title(raw).text;
                id = index->documents.size();
                auto joined = compact(value);
                index->documents.push_back(
                    {makeText(std::move(value)), std::move(joined), {}, {}, {}});
                rawTitles.emplace(raw, id);
            }
            auto& ids = index->documents[id].games;
            if (ids.empty() || ids.back() != i)
                ids.push_back(i);
            return id;
        };
        for (size_t ordered : order) {
            auto& g = games[ordered];
            if (g.collection || !g.countAsGame || !identities.insert(g.id).second)
                continue;
            const size_t i {index->games.size()};
            index->games.push_back(std::move(g));
            const auto& game {index->games.back()};
            const size_t display {addTitle(game.title, i)};
            const size_t sortDoc {!game.sortName.empty() && game.sortName != game.title ?
                                      addTitle(game.sortName, i) :
                                      display};
            const size_t fileDoc {!game.fileStem.empty() && game.fileStem != game.title ?
                                      addTitle(game.fileStem, i) :
                                      display};
            index->gameDocuments.push_back({display, sortDoc, fileDoc});
            std::string metadata;
            metadata.reserve(game.developer.size() + game.publisher.size() + game.genre.size() +
                             game.system.size() + game.systemName.size() + 4);
            for (const auto* field :
                 {&game.developer, &game.publisher, &game.genre, &game.system, &game.systemName}) {
                if (!metadata.empty())
                    metadata += ' ';
                metadata += cached(*field);
            }
            index->metadataGroups[metadata].push_back(i);
            auto& displayDoc {index->documents[display]};
            displayDoc.display = game.title;
            displayDoc.displayGames.push_back(i);
            index->systemGames[game.system].push_back(i);
            index->systems[cached(game.system)].insert(game.system);
            index->systems[cached(game.systemName)].insert(game.system);
            const std::array<size_t, 1> single {i};
            completion(SuggestionKind::Developer, game.developer, single);
            completion(SuggestionKind::Publisher, game.publisher, single);
            completion(SuggestionKind::Genre, game.genre, single);
            completion(SuggestionKind::System, game.systemName, single);
            completion(SuggestionKind::System, game.system, single);
        }
        for (size_t i {0}; i < index->documents.size(); ++i) {
            const auto& doc = index->documents[i];
            const auto& t = doc.text;
            if (!doc.displayGames.empty()) {
                std::set<std::string> unique;
                for (const auto& w : t.tokens)
                    if (unique.insert(w.text).second)
                        completion(SuggestionKind::Word, w.text, doc.displayGames);
                completion(SuggestionKind::Title, doc.display, doc.displayGames, t.value);
            }
            std::vector<std::string> tokens;
            tokens.reserve(t.tokens.size() * 2);
            const auto& joined = doc.compact;
            for (size_t length {1}; length <= 3; ++length)
                for (size_t offset {0}; offset + length <= joined.size(); ++offset)
                    index->grams[gram(joined, offset, length)].push_back(i);
            std::vector<std::string> acronymKeys;
            acronymKeys.reserve(t.tokens.size() * 2);
            std::vector<std::vector<std::string>> initials;
            initials.reserve(t.tokens.size());
            for (const auto& w : t.tokens)
                initials.push_back(letters(w.text));
            for (const auto& w : t.tokens) {
                tokens.push_back(w.text);
                tokens.push_back(number(w.text));
            }
            for (size_t a {0}; a < t.tokens.size(); ++a) {
                for (const auto& first : initials[a]) {
                    if (first.size() >= 2)
                        acronymKeys.push_back(first.substr(0, 2));
                    for (size_t b {a + 1}; b < t.tokens.size(); ++b) {
                        for (const auto& second : initials[b])
                            acronymKeys.push_back((first + second).substr(0, 2));
                        if (!small(t.tokens[b].text))
                            break;
                    }
                }
            }
            std::sort(tokens.begin(), tokens.end());
            tokens.erase(std::unique(tokens.begin(), tokens.end()), tokens.end());
            std::sort(acronymKeys.begin(), acronymKeys.end());
            acronymKeys.erase(std::unique(acronymKeys.begin(), acronymKeys.end()),
                              acronymKeys.end());
            for (const auto& token : tokens) {
                auto& v = index->vocabulary[token];
                if (v.games.empty())
                    v.points = codepoints(token);
                v.games.push_back(i);
            }
            for (const auto& key : acronymKeys)
                index->acronymPrefixes[key].push_back(i);
        }
        // A series must be shared by different titles. Adjacent titles in lexical order
        // expose every shared leading phrase; unique suffixes never allocate suggestions.
        std::vector<size_t> displays;
        for (size_t i {0}; i < index->documents.size(); ++i)
            if (!index->documents[i].displayGames.empty())
                displays.push_back(i);
        std::sort(displays.begin(), displays.end(), [&](size_t a, size_t b) {
            return index->documents[a].text.value < index->documents[b].text.value;
        });
        std::set<std::string> series;
        for (size_t i {1}; i < displays.size(); ++i) {
            const auto& a = index->documents[displays[i - 1]].text;
            const auto& b = index->documents[displays[i]].text;
            if (a.value == b.value)
                continue;
            size_t common {0};
            while (common < a.tokens.size() && common < b.tokens.size() &&
                   a.tokens[common].text == b.tokens[common].text)
                ++common;
            for (size_t n {2}; n <= common; ++n)
                series.insert(a.value.substr(0, n == a.tokens.size() ? a.value.size() :
                                                                       a.tokens[n].offset - 1));
        }
        for (const auto& key : series) {
            auto begin = std::lower_bound(displays.begin(), displays.end(), key,
                                          [&](size_t doc, const std::string& value) {
                                              return index->documents[doc].text.value < value;
                                          });
            std::string spelling;
            for (auto it = begin; it != displays.end(); ++it) {
                const auto& doc = index->documents[*it];
                if (!starts(doc.text.value, key) ||
                    (doc.text.value.size() > key.size() && doc.text.value[key.size()] != ' '))
                    break;
                if (spelling.empty()) {
                    const auto mapping = title(doc.display, true);
                    spelling = doc.display.substr(mapping.source.front().begin,
                                                  mapping.source[key.size() - 1].end -
                                                      mapping.source.front().begin);
                }
                completion(SuggestionKind::Series, spelling, doc.displayGames, key);
            }
        }
        index->sortedTitles.resize(index->documents.size());
        std::iota(index->sortedTitles.begin(), index->sortedTitles.end(), 0);
        std::sort(index->sortedTitles.begin(), index->sortedTitles.end(), [&](size_t a, size_t b) {
            return index->documents[a].compact < index->documents[b].compact;
        });
        for (auto& [word, v] : index->vocabulary) {
            v.text = word;
            index->signatures[v.points.size()][signature(v.points)].push_back(&v);
        }
        auto& cs = index->completions;
        std::sort(cs.begin(), cs.end(), [](const Index::Completion& a, const Index::Completion& b) {
            if (a.weight != b.weight)
                return a.weight > b.weight;
            if (a.kind != b.kind)
                return (a.kind == SuggestionKind::Word ? 99 : static_cast<int>(a.kind)) <
                       (b.kind == SuggestionKind::Word ? 99 : static_cast<int>(b.kind));
            if (a.key != b.key)
                return a.key < b.key;
            return a.text < b.text;
        });
        for (size_t i {0}; i < cs.size(); ++i) {
            const auto kind = cs[i].kind;
            index
                ->completionOrder[kind == SuggestionKind::Word ? 0 :
                                  kind == SuggestionKind::Title || kind == SuggestionKind::Series ?
                                                                 1 :
                                                                 2]
                .push_back(i);
        }
        for (auto& order : index->completionOrder)
            std::sort(order.begin(), order.end(), [&](size_t a, size_t b) {
                if (cs[a].key != cs[b].key)
                    return cs[a].key < cs[b].key;
                return a < b;
            });
        for (size_t i {0}; i < index->games.size(); ++i)
            if (index->games[i].lastPlayed > "19700101T000000")
                index->recent.push_back(i);
        std::stable_sort(index->recent.begin(), index->recent.end(), [&](size_t a, size_t b) {
            return index->games[a].lastPlayed > index->games[b].lastPlayed;
        });
        mIndex = std::move(index);
    }

    std::vector<Match> Core::search(const std::string& query,
                                    size_t limit,
                                    const Filter& filter) const
    {
        return find(query, limit, filter, false);
    }
    Results Core::query(const std::string& query, size_t limit, const Filter& filter) const
    {
        Results result;
        result.matches = find(query, limit, filter, false, nullptr, &result);
        return result;
    }

    std::vector<size_t> Core::browse(size_t limit, const Filter& filter) const
    {
        std::vector<size_t> result;
        for (size_t i {0}; i < mIndex->games.size() && result.size() < limit; ++i)
            if (visible(mIndex->games[i], filter))
                result.push_back(i);
        return result;
    }

    std::vector<Match> Core::closest(const std::string& query,
                                     size_t limit,
                                     const Filter& filter) const
    {
        const auto q = codepoints(normalize(query));
        if (q.empty() || q.size() > 128 || !limit)
            return {};
        // This fallback deliberately has no typo threshold. It is labelled "Did you mean",
        // never mixed into actual matches. Work on the immutable title index, never media.
        std::unordered_map<std::string, size_t> distances;
        auto distance = [&](const std::string& text) {
            const auto cached = distances.find(text);
            if (cached != distances.end())
                return cached->second;
            const auto points = codepoints(text);
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
        std::vector<std::pair<size_t, size_t>> nearest;
        for (const auto& doc : mIndex->documents) {
            if (doc.displayGames.empty())
                continue;
            size_t score = phrase ? distance(doc.text.value) : q.size() + 256;
            for (const auto& token : doc.text.tokens)
                score = std::min(score, distance(token.text));
            for (size_t i : doc.displayGames) {
                if (!visible(mIndex->games[i], filter))
                    continue;
                nearest.emplace_back(score, i);
            }
        }
        const auto retained = std::min(limit, nearest.size());
        std::partial_sort(nearest.begin(), nearest.begin() + retained, nearest.end());
        nearest.resize(retained);
        std::vector<Match> result;
        std::unordered_set<size_t> seen;
        for (const auto& entry : nearest) {
            if (seen.insert(entry.second).second)
                result.push_back({entry.second, MatchClass::Typo, {}});
            if (result.size() == limit)
                break;
        }
        return result;
    }

    std::vector<Match> Core::find(const std::string& query,
                                  size_t limit,
                                  const Filter& filter,
                                  bool firstOnly,
                                  const std::vector<size_t>* support,
                                  Results* counts) const
    {
        const auto& ix = *mIndex;
        std::string q {title(query).text};
        if ((!counts && q.empty()) || !limit)
            return {};
        auto qw {words(q)};
        std::set<std::string> restricted;
        // Longest full alias first, then continue to find additional system aliases.
        for (size_t pos {0}; pos < qw.size();) {
            size_t consumed {0};
            for (size_t end {qw.size()}; end > pos; --end) {
                const auto alias {q.substr(
                    qw[pos].offset, qw[end - 1].offset + qw[end - 1].text.size() - qw[pos].offset)};
                const auto it {ix.systems.find(alias)};
                if (it != ix.systems.end()) {
                    restricted.insert(it->second.begin(), it->second.end());
                    consumed = end - pos;
                    break;
                }
            }
            if (consumed)
                qw.erase(qw.begin() + pos, qw.begin() + pos + consumed);
            else
                ++pos;
        }
        q.clear();
        for (auto& w : qw) {
            if (!q.empty())
                q += ' ';
            w.offset = q.size();
            q += w.text;
        }
        std::vector<uint8_t> supported;
        if (support && support->size() > 16) {
            supported.resize(ix.games.size());
            for (size_t i : *support)
                supported[i] = 1;
        }
        auto allowed = [&](size_t i) {
            const auto& g = ix.games[i];
            return visible(g, filter) && (restricted.empty() || restricted.count(g.system)) &&
                   (supported.empty() || supported[i]);
        };
        // Most title/entity suggestions have just a handful of supporting games. Validate
        // those directly, rather than traversing a global index for every rejected completion.
        if (support && support->size() <= 16) {
            for (size_t i : *support) {
                if (!allowed(i))
                    continue;
                if (q.empty())
                    return {{i, MatchClass::Metadata, {}}};
                for (size_t doc : ix.gameDocuments[i]) {
                    const int r {rank(q, qw, ix.documents[doc].text)};
                    if (r >= 0)
                        return {{i, static_cast<MatchClass>(r), {}}};
                }
                const auto& g = ix.games[i];
                const auto metadata {normalize(g.developer + " " + g.publisher + " " + g.genre +
                                               " " + g.system + " " + g.systemName)};
                if (std::all_of(qw.begin(), qw.end(), [&](const Word& w) {
                        return metadata.find(w.text) != std::string::npos;
                    }))
                    return {{i, MatchClass::Metadata, {}}};
            }
            return {};
        }
        std::vector<int> ranks(ix.games.size(), 9);
        size_t matched {0};
        Match firstMatch {0, MatchClass::Metadata, {}};
        auto apply = [&](const std::vector<size_t>& ids, int r) {
            for (size_t i : ids) {
                if (!allowed(i))
                    continue;
                if (ranks[i] == 9)
                    ++matched;
                ranks[i] = std::min(ranks[i], r);
                if (firstOnly) {
                    firstMatch = {i, static_cast<MatchClass>(r), {}};
                    return;
                }
            }
        };
        // Exact and prefix lookups are independent of corpus size. Once these classes
        // fill the result window no lower class can affect the answer.
        const auto compactQuery {compact(q)};
        const auto begin {std::lower_bound(
            ix.sortedTitles.begin(), ix.sortedTitles.end(), compactQuery,
            [&](size_t doc, const std::string& key) { return ix.documents[doc].compact < key; })};
        if (!q.empty()) {
            for (auto it = begin;
                 it != ix.sortedTitles.end() && ix.documents[*it].compact == compactQuery; ++it) {
                apply(ix.documents[*it].games, 0);
                if (firstOnly && matched)
                    return {firstMatch};
            }
            if ((counts || matched < limit))
                for (auto it = begin;
                     it != ix.sortedTitles.end() && starts(ix.documents[*it].compact, compactQuery);
                     ++it) {
                    apply(ix.documents[*it].games,
                          ix.documents[*it].compact == compactQuery ? 0 : 1);
                    if (firstOnly && matched)
                        return {firstMatch};
                }
        }
        if ((counts || matched < limit) && !q.empty()) {
            std::vector<uint8_t> candidates(ix.documents.size(), 1);
            for (const auto& token : qw) {
                std::vector<uint8_t> found(ix.documents.size(), 0);
                const auto points {codepoints(token.text)};
                const auto numeric {number(token.text)};
                const auto bits {signature(points)};
                const auto threshold {points.size() >= 9 ? 2U : 1U};
                // A substring must contain every byte n-gram of the query. The rarest
                // posting list is enough to bound candidates; verify the complete token.
                const size_t gramLength {std::min(size_t {3}, token.text.size())};
                const std::vector<size_t>* rarest {nullptr};
                bool possible {true};
                for (size_t offset {0}; offset + gramLength <= token.text.size(); ++offset) {
                    auto it = ix.grams.find(gram(token.text, offset, gramLength));
                    if (it == ix.grams.end()) {
                        possible = false;
                        break;
                    }
                    if (!rarest || it->second.size() < rarest->size())
                        rarest = &it->second;
                }
                if (possible && rarest)
                    for (size_t i : *rarest)
                        if (ix.documents[i].compact.find(token.text) != std::string::npos)
                            found[i] = 1;
                if (points.size() >= 5)
                    for (auto length = ix.signatures.lower_bound(points.size() - threshold);
                         length != ix.signatures.end() &&
                         length->first <= points.size() + threshold;
                         ++length)
                        for (const auto& group : length->second) {
                            if (bitCount(bits & ~group.first) > threshold)
                                continue;
                            for (const auto* v : group.second) {
                                if (!near(points, v->points))
                                    continue;
                                for (size_t i : v->games)
                                    found[i] = 1;
                            }
                        }
                const auto numericWord {ix.vocabulary.find(numeric)};
                if (numericWord != ix.vocabulary.end())
                    for (size_t i : numericWord->second.games)
                        found[i] = 1;
                if (token.text.size() >= 2) {
                    const auto it {ix.acronymPrefixes.find(token.text.substr(0, 2))};
                    if (it != ix.acronymPrefixes.end())
                        for (size_t i : it->second)
                            found[i] = 1;
                }
                for (size_t i {0}; i < candidates.size(); ++i)
                    candidates[i] &= found[i];
            }
            for (size_t i {0}; i < ix.documents.size(); ++i) {
                if (!candidates[i])
                    continue;
                const auto& d = ix.documents[i];
                // Exact/prefix matches already have their best possible rank from the
                // index lookup above. Counting every result must not rank them again.
                if (!std::any_of(d.games.begin(), d.games.end(),
                                 [&](size_t game) { return allowed(game) && ranks[game] > 1; }))
                    continue;
                const int r {rank(q, qw, d.text)};
                if (r >= 0) {
                    apply(d.games, r);
                    if (firstOnly && matched)
                        return {firstMatch};
                }
            }
        }
        if (q.empty()) {
            for (const auto& group : ix.systemGames)
                if (restricted.empty() || restricted.count(group.first)) {
                    apply(group.second, 8);
                    if (firstOnly && matched)
                        return {firstMatch};
                }
        }
        else if ((counts || matched < limit))
            for (const auto& group : ix.metadataGroups)
                if (std::all_of(qw.begin(), qw.end(), [&](const Word& w) {
                        return group.first.find(w.text) != std::string::npos;
                    })) {
                    apply(group.second, 8);
                    if (firstOnly && matched)
                        return {firstMatch};
                }
        if (counts) {
            std::map<std::string, SystemCount> systems;
            for (size_t i {0}; i < ranks.size(); ++i) {
                if (ranks[i] == 9)
                    continue;
                ++counts->total;
                const auto& game = ix.games[i];
                auto& system = systems[game.system];
                system.system = game.system;
                system.name = game.systemName;
                ++system.count;
            }
            for (auto& entry : systems)
                counts->systems.push_back(std::move(entry.second));
        }
        std::array<std::vector<size_t>, 9> buckets;
        for (size_t i {0}; i < ranks.size(); ++i)
            if (ranks[i] < 9 && buckets[ranks[i]].size() < limit)
                buckets[ranks[i]].push_back(i);
        std::vector<Match> results;
        for (size_t r {0}; r < buckets.size(); ++r) {
            for (size_t i : buckets[r]) {
                if (results.size() == limit)
                    return results;
                Match match {i, static_cast<MatchClass>(r), {}};
                // Map only selected results, never retain normalized offsets in the UI.
                std::vector<Span> normalizedSpans;
                if (r < 8 && !q.empty() &&
                    rank(q, qw, makeText(title(ix.games[i].title).text), &normalizedSpans,
                         static_cast<int>(r)) == static_cast<int>(r)) {
                    const auto mapped {title(ix.games[i].title, true)};
                    for (auto s : normalizedSpans)
                        if (s.begin < s.end && s.end <= mapped.source.size())
                            match.spans.push_back(
                                {mapped.source[s.begin].begin, mapped.source[s.end - 1].end});
                    mergeSpans(match.spans);
                }
                results.push_back(std::move(match));
            }
        }
        return results;
    }

    std::vector<Suggestion> Core::suggest(const std::string& query,
                                          size_t limit,
                                          const Filter& filter) const
    {
        const auto q {normalize(query)};
        if (!limit)
            return {};
        if (q.empty()) {
            std::vector<Suggestion> result;
            std::set<std::string> seen;
            for (const auto& c : mIndex->completions) {
                if (c.kind == SuggestionKind::Word || c.kind == SuggestionKind::Title ||
                    !seen.insert(c.key).second)
                    continue;
                if (std::any_of(c.games.begin(), c.games.end(),
                                [&](size_t i) { return visible(mIndex->games[i], filter); }))
                    result.push_back({c.kind, c.text});
                if (result.size() == limit)
                    break;
            }
            return result;
        }
        const bool trailing {query.back() == ' '};
        const auto split {q.rfind(' ')};
        const std::string prefix {trailing                   ? q + " " :
                                  split == std::string::npos ? "" :
                                                               q.substr(0, split + 1)};
        const std::string partial {trailing                   ? "" :
                                   split == std::string::npos ? q :
                                                                q.substr(split + 1)};
        std::vector<Suggestion> result;
        std::unordered_set<std::string> seen;
        std::vector<size_t> candidates;
        const std::array<std::string, 3> prefixes {partial, title(query).text, q};
        for (size_t group {0}; group < prefixes.size(); ++group) {
            if (prefixes[group].empty())
                continue;
            const auto& order = mIndex->completionOrder[group];
            const auto& prefix = prefixes[group];
            auto begin = std::lower_bound(order.begin(), order.end(), prefix,
                                          [&](size_t i, const std::string& value) {
                                              return mIndex->completions[i].key < value;
                                          });
            for (auto it = begin; it != order.end() && starts(mIndex->completions[*it].key, prefix);
                 ++it)
                candidates.push_back(*it);
        }
        std::sort(candidates.begin(), candidates.end());
        for (size_t candidate : candidates) {
            const auto& c = mIndex->completions[candidate];

            std::string insert;
            if (c.kind == SuggestionKind::Word) {
                if (partial.empty() || !starts(c.key, partial))
                    continue;
                insert = prefix + c.text;
            }
            else {
                insert = c.text;
            }
            const auto key {normalize(insert)};
            if (key == q || seen.count(key))
                continue;
            if (!std::any_of(c.games.begin(), c.games.end(),
                             [&](size_t i) { return visible(mIndex->games[i], filter); }))
                continue;
            // A completion is useful only if the inserted query actually has visible matches,
            // including system restrictions and the preceding tokens of word completions.
            if (find(insert, 1, filter, true, &c.games).empty())
                continue;
            seen.insert(key);
            result.push_back({c.kind, insert});
            if (result.size() == limit)
                break;
        }
        return result;
    }

    std::vector<size_t> Core::recentlyPlayed(size_t limit, const Filter& filter) const
    {
        std::vector<size_t> result;
        for (size_t i : mIndex->recent) {
            if (result.size() == limit)
                break;
            if (visible(mIndex->games[i], filter))
                result.push_back(i);
        }
        return result;
    }
} // namespace LibrarySearch
