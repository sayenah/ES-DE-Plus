//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  policy.cpp
//  Written for ES-DE-Plus. Fixtures are original, using the upstream themes.json format.

#include "ThemeRepositoryFuse.h"
#include "ThemeRepositoryTrust.h"

#include <iostream>
#include <stdexcept>

namespace
{
    void check(bool condition, const char* label)
    {
        if (!condition)
            throw std::runtime_error(label);
    }
} // namespace

int main()
{
    const ThemeRepositoryFuse::Values initial {{"core.repositoryformatversion", "0"},
                                               {"core.bare", "false"},
                                               {"core.logallrefupdates", "true"},
                                               {"core.filemode", "false"},
                                               {"core.symlinks", "false"},
                                               {"core.ignorecase", "true"}};
    check(ThemeRepositoryFuse::initKeys(initial), "complete Android init meaning");
    for (const auto& key :
         {"core.bare", "core.repositoryformatversion", "core.logallrefupdates", "core.filemode"}) {
        auto changed = initial;
        changed.erase(key);
        check(!ThemeRepositoryFuse::initKeys(changed), "required init key cannot disappear");
    }
    auto hostile = initial;
    hostile["core.worktree"] = "/outside";
    check(!ThemeRepositoryFuse::initKeys(hostile), "unknown init keys rejected");
    for (int api : {31, 32}) {
        check(ThemeRepositoryFuse::missingOrigin(api, true, true, true, true),
              "narrow missing-origin positive");
        for (int missing {0}; missing < 4; ++missing)
            check(!ThemeRepositoryFuse::missingOrigin(api, missing != 0, missing != 1, missing != 2,
                                                      missing != 3),
                  "every classifier prerequisite required");
    }
    for (int api : {0, 30, 33, 34, 36})
        check(!ThemeRepositoryFuse::missingOrigin(api, true, true, true, true),
              "Android 12 classifier never inferred on another platform");
    using namespace ThemeRepositoryTrust;
    check(validName("Plus-original_1.2"), "ordinary component positive control");
    for (const std::string name :
         {"", ".", "..", ".git", "../escape", "a/b", "a\\b", "*", "space name", "a\nb", "a\rb",
          "a\tb", "foo_DISABLED", "foo_disabled", "caf\xc3\xa9"})
        check(!validName(name), "invalid component");
    check(!validName(std::string("foo\0bar", 7)), "full embedded NUL");
    const size_t limit {255 - std::string("-master_9_WRONG_URL_DISABLED").size()};
    check(validName(std::string(limit, 'a')), "recoverable component length positive control");
    check(!validName(std::string(limit + 1, 'a')), "recovery suffix room");
    check(filesystemNames(std::string(limit, 'a')).rbegin()->size() <= 255,
          "filesystem component bound");
    for (const auto& pair : std::vector<std::pair<std::string, std::string>> {
             {"foo", "foo"}, {"foo", "FOO"}, {"foo", "foo-main"}, {"foo", "FOO-master"}}) {
        auto result = admission({{pair.first, "https://example.invalid/a"},
                                 {pair.second, "https://example.invalid/b"}});
        check(!result[0] && !result[1], "reject every colliding entry");
    }
    for (const std::string reserved : {"themes-list", "THEMES-LIST", "themes-list-main",
                                       "THEMES-LIST-master", "foo_1_WRONG_URL_DISABLED"})
        check(!admission({{reserved, "https://example.invalid/a"}})[0], "reserved namespace");
    auto ordinary = admission({{"original-one", "https://example.invalid/a"},
                               {"original-two", "https://example.invalid/b"}});
    check(ordinary[0] && ordinary[1], "unambiguous admission positive control");
    rapidjson::Document document;
    document.Parse(R"({"themes":[{"reponame":"original","url":"https://example.invalid/a"},
        {"reponame":"original\u0000escape","url":"https://example.invalid/b"},
        {"reponame":"control\u001fname","url":"https://example.invalid/c"},
        {"reponame":"../escape","url":"https://example.invalid/d"},
        {"reponame":"THEMES-LIST","url":"https://example.invalid/e"},
        {"reponame":"duplicate","url":"https://example.invalid/f"}],
        "themesAndroid":[{"reponame":"DUPLICATE","url":"https://example.invalid/g"}]})");
    check(!document.HasParseError(), "real RapidJSON parser positive control");
    const auto entries = jsonEntries(document);
    check(entries.size() == 7 && entries[1].first.size() == 15, "JSON length is preserved");
    const auto accepted = admission(entries);
    check(accepted[0], "real JSON admitted positive control");
    for (size_t i {1}; i < accepted.size(); ++i)
        check(!accepted[i], "hostile real JSON entry rejected");
    std::string config;
    check(configText("/data/# ; \"quoted\" \\ caf\xc3\xa9", {"themes-list", "original"}, config),
          "config escaping positive control");
    check(config ==
              "[safe]\n\tdirectory = \"/data/# ; \\\"quoted\\\" \\\\ caf\xc3\xa9/themes-list\"\n"
              "\tdirectory = \"/data/# ; \\\"quoted\\\" \\\\ caf\xc3\xa9/original\"\n",
          "literal exact-path Git config quoting");
    for (const std::string root : {"", "/", "relative", "/data/", "/data\ninject", "/data\r"})
        check(!configText(root, {"themes-list"}, config) && config.empty(), "invalid config root");
    check(!configText("/data", {"*"}, config), "no wildcard safe.directory");
    std::cout
        << "PASS: name admission, complete JSON strings, aliases, recovery namespace, escaping\n";
}
