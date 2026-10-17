//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  emulator-manager-probe.cpp
//
//  Written for ES-DE-Plus. Exercises production XML preservation and save checkpoints.
//

#include "EmulatorLaunchProfile.h"
#include "EmulatorManagerConfig.h"

#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <sys/stat.h>
#include <unistd.h>

namespace
{
    void require(bool value, const std::string& message)
    {
        if (!value)
            throw std::runtime_error(message);
    }
    std::string read(const std::string& path)
    {
        std::ifstream input {path};
        return {std::istreambuf_iterator<char>(input), {}};
    }
    void put(const std::string& path, const std::string& text)
    {
        std::ofstream out {path};
        out << text;
        require(out.good(), "fixture write");
    }
    std::string tree(const std::string& bytes)
    {
        pugi::xml_document document;
        require(document.load_buffer(bytes.data(), bytes.size(), pugi::parse_full), "tree parse");
        std::ostringstream output;
        document.print(output, "", pugi::format_raw);
        return output.str();
    }
    template <typename F> void refused(F action)
    {
        try {
            action();
        }
        catch (const std::runtime_error&) {
            return;
        }
        throw std::runtime_error("rejection control escaped");
    }
} // namespace

int main(int argc, char** argv)
{
    try {
        require(argc == 2, "fresh scratch directory required");
        std::string root {argv[1]};
        require(mkdir(root.c_str(), 0700) == 0, "scratch must be new");
        const std::string bundle {root + "/bundle.xml"};
        const std::string bundledRules {root + "/bundle-rules.xml"};
        const std::string systems {root + "/es_systems.xml"};
        const std::string rules {root + "/es_find_rules.xml"};
        const std::string source {"<systemList><system><name>test</name><fullname>Test</fullname>"
                                  "<path>%ROMPATH%/test</path><extension>.rom</extension>"
                                  "<command>PLACEHOLDER %ROM%</command><theme>test</theme>"
                                  "</system></systemList>"};
        put(bundle, source);
        put(bundledRules, "<ruleList><emulator name='EXISTING'><rule type='androidpackage'>"
                          "<entry>org.example/Activity</entry></rule></emulator></ruleList>");
        const std::string custom {
            "<!--user comment--><loadExclusive/><systemList private='keep'>"
            "<system><name>test</name><fullname>Custom</fullname>"
            "<path>%ROMPATH%/test</path><extension>.rom</extension>"
            "<command>PLACEHOLDER %ROM%</command><unknown a='b'>keep</unknown>"
            "</system></systemList>"};
        put(systems, custom);
        EmulatorManagerConfig config {root, bundle, bundledRules};
        require(config.systems().size() == 1 && config.system("test").fullName == "Custom",
                "precedence");
        refused([&] {
            config.add("test", "Fork", "org.example/Activity", "%EMULATOR_X% %DATA%=%ROM%",
                       ".zip .ZIP", false);
        });
        const auto id = config.add("test", "Fork", "org.example/Activity",
                                   "%EMULATOR_X% %DATA%=%ROM%", ".zip .ZIP", true);
        config.setSaveCheckpoint([](int point) {
            if (point == 1)
                throw std::runtime_error("injected between replacements");
        });
        refused([&] { config.save(); });
        require(read(systems) == custom, "systems unchanged on partial save");
        pugi::xml_document ruleDoc;
        require(ruleDoc.load_file(rules.c_str()), "partial rules parseable");
        require(read(rules).find(id) != std::string::npos, "rule written first");
        config.setSaveCheckpoint({});
        config.save();
        EmulatorManagerConfig after {root, bundle, bundledRules};
        const auto actual = after.system("test");
        require(actual.commands.size() == 2 && actual.extensions == ".rom .zip .ZIP",
                "add readback");
        require(actual.commands[1].addition == id, "ownership readback");
        require(read(systems).find("user comment") != std::string::npos &&
                    read(systems).find("<unknown a='b'>keep</unknown>") != std::string::npos &&
                    read(systems).find("loadExclusive") != std::string::npos &&
                    read(systems).find("private='keep'") != std::string::npos,
                "custom preservation");
        after.remove("test", id);
        after.save();
        require(EmulatorManagerConfig(root, bundle, bundledRules).system("test").commands.size() ==
                    1,
                "remove only addition");
        after.reset("test");
        after.save();
        require(EmulatorManagerConfig(root, bundle, bundledRules).system("test").fullName ==
                        "Test" &&
                    read(systems).find("loadExclusive") != std::string::npos,
                "exclusive reset retains bundled snapshot and directive");
        // External edits are detected with exact bytes, before either replacement.
        EmulatorManagerConfig concurrent {root, bundle, bundledRules};
        const auto previousRules = read(rules);
        put(systems, custom + "<!--intervening edit-->");
        refused([&] { concurrent.save(); });
        require(read(rules) == previousRules, "external edit preserves rules");
        put(systems, "<systemList><system><name>test</name></system><system><name>test</name></"
                     "system></systemList>");
        refused([&] { EmulatorManagerConfig bad(root, bundle, bundledRules); });
        put(systems, "<broken");
        refused([&] { EmulatorManagerConfig bad(root, bundle, bundledRules); });
        put(systems, "<systemList/>");
        EmulatorManagerConfig snapshot {root, bundle, bundledRules};
        snapshot.add("test", "Fork", "org.example/Activity", "%EMULATOR_X% %DATA%=%ROM%",
                     ".zip .ZIP", true);
        snapshot.save();
        require(!EmulatorManagerConfig(root, bundle, bundledRules).system("test").stale,
                "fresh snapshot");
        // A SAF-mode variant change is stale even when this individual entry is identical.
        const std::string safBundle {root + "/bundle-saf.xml"};
        put(safBundle, source);
        const auto beforeModeChange = read(systems);
        EmulatorManagerConfig safMode {root, safBundle, bundledRules};
        require(safMode.system("test").stale && read(systems) == beforeModeChange,
                "SAF variant change reports staleness without rewriting");
        safMode.refresh("test");
        safMode.save();
        require(!EmulatorManagerConfig(root, safBundle, bundledRules).system("test").stale &&
                    EmulatorManagerConfig(root, safBundle, bundledRules)
                            .system("test")
                            .commands.size() == 2,
                "explicit SAF variant refresh preserves manager addition");
        EmulatorManagerConfig normalMode {root, bundle, bundledRules};
        require(normalMode.system("test").stale, "switch back to normal variant is stale");
        normalMode.refresh("test");
        normalMode.save();
        auto newer = source;
        newer.replace(newer.find("<fullname>Test"), 14, "<fullname>New ");
        put(bundle, newer);
        EmulatorManagerConfig update {root, bundle, bundledRules};
        require(update.system("test").stale, "updated bundle detected");
        update.refresh("test");
        update.save();
        auto refreshed = EmulatorManagerConfig(root, bundle, bundledRules).system("test");
        require(!refreshed.stale && refreshed.commands.size() == 2 &&
                    refreshed.extensions.find(".ZIP") != std::string::npos,
                "refresh preserves addition and types");
        auto handEdit = read(systems);
        handEdit.replace(handEdit.find("<fullname>"), 10, "<fullname>Hand edited ");
        put(systems, handEdit);
        EmulatorManagerConfig edited {root, bundle, bundledRules};
        refused([&] { edited.refresh("test"); });
        require(read(systems) == handEdit, "refused refresh preserves hand edits");
        edited.reset("test");
        edited.save();
        require(!EmulatorManagerConfig(root, bundle, bundledRules).system("test").custom,
                "reset readback");
        const std::string collisionProfile {"%EMULATOR_X% %DATA%=%ROM%"};
        const auto colliding =
            "ESDEPLUS_" + EmulatorManagerConfig::fingerprint(
                              "test\nCollision\norg.example/Activity\n" + collisionProfile);
        auto collisionRules = read(rules);
        collisionRules.insert(
            collisionRules.find("</ruleList>"),
            "<emulator name='" + colliding +
                "'><rule type='androidpackage'><entry>org.other/Keep</entry></rule></emulator>");
        put(rules, collisionRules);
        EmulatorManagerConfig collision {root, bundle, bundledRules};
        auto collisionId = collision.add("test", "Collision", "org.example/Activity",
                                         collisionProfile, ".zip", true);
        require(collisionId != colliding, "rule collision gets independent ID");
        collision.setSaveCheckpoint([](int point) {
            if (point == 0)
                throw std::runtime_error("injected before replacement");
        });
        const auto collisionBefore = read(systems);
        refused([&] { collision.save(); });
        require(read(systems) == collisionBefore && read(rules) == collisionRules,
                "before-save failure leaves both files unchanged");
        collision.setSaveCheckpoint([](int point) {
            if (point == 2)
                throw std::runtime_error("injected after replacements before apply");
        });
        refused([&] { collision.save(); });
        require(EmulatorManagerConfig(root, bundle, bundledRules).system("test").commands.size() ==
                    2,
                "post-save failure remains parseable with exactly one addition");
        collision.setSaveCheckpoint({});
        collision.save();
        require(read(rules).find("org.other/Keep") != std::string::npos,
                "colliding pre-existing rule preserved");
        const auto collisionSystem = read(systems);
        EmulatorManagerConfig duplicate {root, bundle, bundledRules};
        refused([&] {
            duplicate.add("test", "Collision", "org.example/Activity", collisionProfile, ".ZIP",
                          true);
        });
        require(read(systems) == collisionSystem &&
                    read(rules).find("org.other/Keep") != std::string::npos,
                "duplicate label refusal preserves files");
        // A cloned draft retains its opening snapshot, rather than adopting an external edit.
        EmulatorManagerConfig opening {root, bundle, bundledRules};
        put(systems, collisionSystem + "<!-- external -->");
        auto copiedDraft = opening;
        refused([&] { copiedDraft.save(); });
        put(systems, collisionSystem);
        // A later edit to a tracked command is preserved and not removed by ownership guessing.
        pugi::xml_document editedTree;
        require(editedTree.load_string(collisionSystem.c_str(),
                                       pugi::parse_full | pugi::parse_ws_pcdata),
                "hand-edit fixture parse");
        auto editedNode = editedTree.child("systemList")
                              .child("system")
                              .find_child_by_attribute("command", "label", "Collision");
        editedNode.text().set((std::string {"hand-edited "} + editedNode.text().get()).c_str());
        std::ostringstream editedOutput;
        editedTree.print(editedOutput, "", pugi::format_raw);
        const auto editedCommand = editedOutput.str();
        put(systems, editedCommand);
        EmulatorManagerConfig ownedEdit {root, bundle, bundledRules};
        refused([&] { ownedEdit.remove("test", collisionId); });
        require(read(systems) == editedCommand, "later hand-edited addition preserved");
        // Preserve the original XML encoding as well as its untouched lexical content.
        pugi::xml_document unicode;
        require(unicode.load_string(source.c_str()), "UTF-16 source preparation");
        unicode.prepend_child(pugi::node_declaration).append_attribute("encoding") = "UTF-16";
        require(unicode.save_file(systems.c_str(), "    ", pugi::format_default,
                                  pugi::encoding_utf16_le),
                "UTF-16 fixture write");
        EmulatorManagerConfig encoded {root, bundle, bundledRules};
        refused([&] {
            encoded.add("test", std::string("Bad\0Label", 9), "org.example/Activity",
                        collisionProfile, ".zip", true);
        });
        encoded.add("test", "Encoded", "org.example/Activity", collisionProfile, ".zip", true);
        encoded.save();
        pugi::xml_document encodedReadback;
        const auto encodedBytes = read(systems);
        const auto encodedResult =
            encodedReadback.load_buffer(encodedBytes.data(), encodedBytes.size(), pugi::parse_full);
        require(encodedResult && encodedResult.encoding == pugi::encoding_utf16_le &&
                    std::string(encodedReadback.child("xml").attribute("encoding").value()) ==
                        "UTF-16",
                "original UTF-16 encoding and declaration retained");
        require(EmulatorManagerConfig(root, bundle, bundledRules).system("test").commands.size() ==
                    2,
                "encoded input readback");
        const auto validSystems = read(systems);
        const auto validRules = read(rules);
        require(chmod(systems.c_str(), 0000) == 0, "unreadable regular override fixture");
        refused([&] { EmulatorManagerConfig denied(root, bundle, bundledRules); });
        require(chmod(systems.c_str(), 0600) == 0 && read(systems) == validSystems &&
                    read(rules) == validRules,
                "unreadable regular override leaves both files unchanged");
        require(std::remove(systems.c_str()) == 0 && mkdir(systems.c_str(), 0700) == 0,
                "unreadable override obstacle");
        refused([&] { EmulatorManagerConfig unreadable(root, bundle, bundledRules); });
        require(read(rules) == validRules && rmdir(systems.c_str()) == 0,
                "unreadable override refusal leaves rules unchanged");
        require(symlink(bundle.c_str(), systems.c_str()) == 0, "override symlink fixture");
        refused([&] { EmulatorManagerConfig linked(root, bundle, bundledRules); });
        require(read(bundle) == newer && read(rules) == validRules &&
                    std::remove(systems.c_str()) == 0,
                "symlink refusal preserves destination and rules");
        put(systems, "<systemList><system><name>test</name><fullname>Test</fullname>"
                     "<path>%ROMPATH%/test</path><extension>.rom</extension>"
                     "<command label='Same'>one</command>"
                     "<command label='Same'>two</command></system></systemList>");
        const auto ambiguousSystems = read(systems);
        EmulatorManagerConfig ambiguous {root, bundle, bundledRules};
        refused([&] {
            ambiguous.add("test", "New", "org.example/Activity", collisionProfile, ".zip", true);
        });
        require(read(systems) == ambiguousSystems && read(rules) == validRules,
                "ambiguous duplicate command labels leave both files unchanged");
        put(systems, validSystems);
        EmulatorManagerConfig intervening {root, bundle, bundledRules};
        intervening.add("test", "Intervening", "org.example/Activity", collisionProfile, ".ZIP",
                        true);
        intervening.setSaveCheckpoint([&](int point) {
            if (point == 1)
                put(systems, validSystems + "<!-- edit between replacements -->");
        });
        refused([&] { intervening.save(); });
        require(
            read(systems) == validSystems + "<!-- edit between replacements -->" &&
                EmulatorManagerConfig(root, bundle, bundledRules).system("test").commands.size() ==
                    2,
            "edit between replacements is preserved without publishing dangling command");
        const auto gamelist = root + "/gamelist.xml";
        put(gamelist,
            "<!-- user gamelist "
            "--><alternativeEmulator><label>Removed</label></alternativeEmulator><gameList "
            "extra='preserve'><game><path>./one.zip</path><altemulator>Removed</"
            "altemulator><playcount>7</playcount></game><game><path>./two.zip</"
            "path><altemulator>Unrelated</altemulator></game></gameList>");
        EmulatorManagerConfig::clearSelections(gamelist, {"Removed"});
        pugi::xml_document selectionDoc;
        require(selectionDoc.load_file(gamelist.c_str()), "repaired selections parseable");
        require(std::string(selectionDoc.child("alternativeEmulator").child("label").text().get())
                    .empty(),
                "affected system selection repaired");
        require(std::string(
                    selectionDoc.child("gameList").child("game").child("altemulator").text().get())
                    .empty(),
                "affected game repaired");
        require(std::string(selectionDoc.child("gameList")
                                .child("game")
                                .next_sibling("game")
                                .child("altemulator")
                                .text()
                                .get()) == "Unrelated",
                "unrelated game selection preserved");
        require(read(gamelist).find("user gamelist") != std::string::npos &&
                    read(gamelist).find("<playcount>7</playcount>") != std::string::npos &&
                    read(gamelist).find("extra='preserve'") != std::string::npos,
                "selection repair preserves metadata/comments/attributes");
        const auto once = read(gamelist);
        EmulatorManagerConfig::clearSelections(gamelist, {"Removed"});
        require(read(gamelist) == once, "repair retry idempotent");
        require(EmulatorLaunchProfile::receivers("org.original/.Game", "org.fork") ==
                    std::vector<std::string>({"org.fork.Game", "org.original.Game"}),
                "fork package and preserved namespace receiver candidates");
        require(EmulatorLaunchProfile::receivers("org.original/com.shared.Game", "org.fork") ==
                    std::vector<std::string>({"com.shared.Game"}),
                "independent activity namespace preserved");
        const std::string aliasDirectory {root + "/aliases"};
        require(mkdir(aliasDirectory.c_str(), 0700) == 0, "alias fixture directory");
        EmulatorManagerConfig aliases {aliasDirectory, bundle, bundledRules};
        const std::string alias {"org.example/org.example.HandlerAlias_雪"};
        aliases.add("test", "Alias", alias, collisionProfile, ".zip", true);
        aliases.save();
        EmulatorManagerConfig aliasReadback {aliasDirectory, bundle, bundledRules};
        require(aliasReadback.profileTargets(aliasReadback.system("test").commands.back().value) ==
                    std::vector<std::string>({alias}),
                "arbitrary Unicode alias name preserved through standard find rules");
        const auto aliasSystemsBefore = read(aliasDirectory + "/es_systems.xml");
        const auto aliasRulesBefore = read(aliasDirectory + "/es_find_rules.xml");
        for (const auto& invalid :
             {std::string {"org.example/"}, std::string {"../outside/Activity"},
              std::string {"org.example/Activity\nInjected"},
              std::string {"org.example/Activity"} + '\0' + "Injected"}) {
            refused([&] {
                aliasReadback.add("test", "Invalid", invalid, collisionProfile, ".zip", true);
            });
        }
        require(read(aliasDirectory + "/es_systems.xml") == aliasSystemsBefore &&
                    read(aliasDirectory + "/es_find_rules.xml") == aliasRulesBefore,
                "invalid components leave both override files unchanged");
        // Exact ownership must survive neighbouring user nodes. Ambiguous labels
        // refuse the operation before any configuration or selection repair is saved.
        const auto ownership = root + "/ownership";
        require(mkdir(ownership.c_str(), 0700) == 0, "ownership scratch");
        put(ownership + "/es_systems.xml", source);
        EmulatorManagerConfig owned {ownership, bundle, bundledRules};
        const auto firstId =
            owned.add("test", "First", "org.first/Activity", collisionProfile, "", true);
        const auto secondId =
            owned.add("test", "Second", "org.second/Activity", collisionProfile, "", true);
        owned.save();
        const auto ownedBytes = read(ownership + "/es_systems.xml");
        const auto ownedRules = read(ownership + "/es_find_rules.xml");
        for (bool before : {true, false}) {
            pugi::xml_document doc;
            require(doc.load_string(ownedBytes.c_str(), pugi::parse_full), "duplicate fixture");
            auto system = doc.child("systemList").child("system");
            auto target = system.find_child_by_attribute("command", "label", "First");
            auto user = before ? system.insert_child_before("command", target.previous_sibling()) :
                                 system.insert_child_after("command", target);
            user.append_attribute("label").set_value("First");
            user.text().set("%EMULATOR_EXISTING% %ACTION%=user.choice");
            if (before) {
                auto neighbour = system.insert_child_before("command", user);
                neighbour.append_attribute("label").set_value("User neighbour");
                neighbour.text().set("%EMULATOR_EXISTING% %ACTION%=keep.neighbour");
                system.insert_child_before(pugi::node_comment, neighbour)
                    .set_value("user neighbour");
            }
            else {
                system.insert_child_before(pugi::node_comment, user).set_value("user neighbour");
            }
            std::ostringstream out;
            doc.print(out, "", pugi::format_raw);
            put(ownership + "/es_systems.xml", out.str());
            EmulatorManagerConfig ambiguous {ownership, bundle, bundledRules};
            refused([&] { ambiguous.remove("test", firstId); });
            ambiguous.save();
            require(tree(read(ownership + "/es_systems.xml")) == tree(out.str()) &&
                        tree(read(ownership + "/es_find_rules.xml")) == tree(ownedRules),
                    "same-label user command before/after: complete trees preserved on refusal");
        }
        for (bool userComment : {false, true}) {
            pugi::xml_document doc;
            require(doc.load_string(ownedBytes.c_str(), pugi::parse_full), "owned fixture");
            auto system = doc.child("systemList").child("system");
            auto target = system.find_child_by_attribute("command", "label", "First");
            auto marker = target.previous_sibling();
            if (userComment)
                system.insert_child_before(pugi::node_comment, target)
                    .set_value("keep immediately before addition");
            std::ostringstream input;
            doc.print(input, "", pugi::format_raw);
            put(ownership + "/es_systems.xml", input.str());
            system.remove_child(marker);
            system.remove_child(target);
            std::ostringstream expected;
            doc.print(expected, "", pugi::format_raw);
            EmulatorManagerConfig removal {ownership, bundle, bundledRules};
            removal.remove("test", firstId);
            removal.save();
            require(tree(read(ownership + "/es_systems.xml")) == tree(expected.str()) &&
                        tree(read(ownership + "/es_find_rules.xml")) == tree(ownedRules),
                    "only exact owned command and marker removed; other addition/user comment "
                    "untouched");
            require(EmulatorManagerConfig(ownership, bundle, bundledRules)
                            .system("test")
                            .commands.back()
                            .addition == secondId,
                    "second manager addition retains independent ownership");
        }
        const auto cycles = root + "/rule-cycles";
        require(mkdir(cycles.c_str(), 0700) == 0, "cycle scratch");
        std::string stable;
        std::string stableRules;
        for (int cycle {0}; cycle < 6; ++cycle) {
            EmulatorManagerConfig addition {cycles, bundle, bundledRules};
            const auto id =
                addition.add("test", "Repeat", "org.repeat/Activity", collisionProfile, "", true);
            addition.save();
            if (cycle == 0) {
                stable = id;
                stableRules = read(cycles + "/es_find_rules.xml");
            }
            require(id == stable && tree(read(cycles + "/es_find_rules.xml")) == tree(stableRules),
                    "add/remove/reset cycles reuse identical stable rule without suffix growth");
            EmulatorManagerConfig cleanup {cycles, bundle, bundledRules};
            if (cycle % 2)
                cleanup.reset("test");
            else
                cleanup.remove("test", id);
            cleanup.save();
        }
        EmulatorManagerConfig sharedRule {cycles, bundle, bundledRules};
        const auto sharedFirst = sharedRule.add("test", "Shared first", "org.repeat/Activity",
                                                collisionProfile, "", true);
        const auto sharedSecond = sharedRule.add("test", "Shared second", "org.repeat/Activity",
                                                 collisionProfile, "", true);
        require(sharedFirst != sharedSecond, "shared rule keeps distinct ownership identities");
        sharedRule.save();
        require(tree(read(cycles + "/es_find_rules.xml")) == tree(stableRules),
                "new labels reuse identical recipient rule without accumulation");
        sharedRule.remove("test", sharedFirst);
        sharedRule.save();
        const auto sharedSurvivor =
            EmulatorManagerConfig(cycles, bundle, bundledRules).system("test");
        require(sharedSurvivor.commands.back().addition == sharedSecond &&
                    sharedRule.profileTargets(sharedSurvivor.commands.back().value) ==
                        std::vector<std::string> {"org.repeat/Activity"} &&
                    tree(read(cycles + "/es_find_rules.xml")) == tree(stableRules),
                "removal preserves shared rule and other addition identity");
        const auto formatting = root + "/formatting";
        require(mkdir(formatting.c_str(), 0700) == 0, "formatting scratch");
        auto indented = source;
        indented.replace(indented.find("<command>"), 9, "<command label='Original'>");
        indented.replace(indented.find("<system>"), 8, "\r\n  <system>");
        indented.replace(indented.find("</systemList>"), 13, "\r\n</systemList>\r\n");
        indented = "<?xml version='1.0' encoding='UTF-8'?>\r\n" + indented;
        put(formatting + "/es_systems.xml", indented);
        EmulatorManagerConfig pretty {formatting, bundle, bundledRules};
        const auto prettyId =
            pretty.add("test", "Pretty", "org.pretty/Activity", collisionProfile, "", true);
        pretty.save();
        const auto output = read(formatting + "/es_systems.xml");
        require(output.find("?>\r\n<systemList>") != std::string::npos &&
                    output.find("\r\n  <system>") != std::string::npos &&
                    output.find("\r\n    <command label=\"Pretty\"") != std::string::npos,
                "declaration newline and surrounding two-space indentation retained for new nodes");
        for (size_t i {0}; i < output.size(); ++i)
            require(output[i] != '\n' || (i > 0 && output[i - 1] == '\r'),
                    "uniform CRLF preserved");
        EmulatorManagerConfig prettyReadback {formatting, bundle, bundledRules};
        require(prettyReadback.system("test").commands.back().addition == prettyId,
                "ownership survives pretty-printed whitespace");
        prettyReadback.remove("test", prettyId);
        prettyReadback.save();
        require(tree(read(formatting + "/es_systems.xml")) == tree(indented),
                "formatting and removal preserve complete unowned XML tree");
        const std::string opaque {"<opaque xml:space='preserve'><a/> <b/> </opaque>"
                                  "<mixed>before<a/> <b/>after</mixed>"
                                  "<unknown><a/> \t<b/></unknown>"
                                  "<cdata><![CDATA[  x < y\n ]]></cdata>"};
        auto protectedNodes = [](const std::string& bytes, bool rules, bool whole = false) {
            pugi::xml_document doc;
            require(doc.load_buffer(bytes.data(), bytes.size(),
                                    pugi::parse_full | pugi::parse_ws_pcdata),
                    "significant text parse");
            auto parent = rules ? doc.child("ruleList").child("emulator") :
                                  doc.child("systemList").child("system");
            require(parent, "significant text parent");
            std::ostringstream output;
            if (whole) {
                parent.print(output, "", pugi::format_raw);
            }
            else {
                for (const auto* name : {"opaque", "mixed", "unknown", "cdata"})
                    parent.child(name).print(output, "", pugi::format_raw);
                if (!rules)
                    parent.child("rule").print(output, "", pugi::format_raw);
            }
            return output.str();
        };
        for (bool inherited : {false, true}) {
            const auto significant = root + (inherited ? "/inherited-space" : "/significant");
            require(mkdir(significant.c_str(), 0700) == 0, "significant scratch");
            auto withText = source;
            withText.replace(withText.find("<command>"), 9, "<command label='Original'>");
            // A familiar tag in an unknown position is still opaque user data.
            withText.insert(withText.find("</system>"), opaque + "<rule><a/> <b/></rule>");
            std::string userRules {"<ruleList><emulator name='User'>"
                                   "<rule type='androidpackage'><entry>org.user/Activity</entry>"
                                   "</rule>" +
                                   opaque + "</emulator></ruleList>"};
            if (inherited) {
                withText.replace(withText.find("<systemList>"), 12,
                                 "<systemList xml:space='preserve'> \t");
                withText.replace(withText.find("<system>"), 8, "<system> \t");
                userRules.replace(0, 10, "<ruleList xml:space='preserve'> \t");
            }
            put(significant + "/es_systems.xml", withText);
            put(significant + "/es_find_rules.xml", userRules);
            EmulatorManagerConfig significantConfig {significant, bundle, bundledRules};
            const auto significantId = significantConfig.add(
                "test", "Significant", "org.space/Activity", collisionProfile, "", true);
            significantConfig.save();
            require(protectedNodes(read(significant + "/es_systems.xml"), false) ==
                            protectedNodes(withText, false) &&
                        protectedNodes(read(significant + "/es_find_rules.xml"), true) ==
                            protectedNodes(userRules, true),
                    "mixed, opaque, CDATA and xml:space content unchanged on add");
            EmulatorManagerConfig significantReadback {significant, bundle, bundledRules};
            significantReadback.remove("test", significantId);
            significantReadback.save();
            require(protectedNodes(read(significant + "/es_systems.xml"), false, inherited) ==
                            protectedNodes(withText, false, inherited) &&
                        protectedNodes(read(significant + "/es_find_rules.xml"), true, inherited) ==
                            protectedNodes(userRules, true, inherited),
                    "complete protected subtrees unchanged after readback/removal");
        }
        // LOW-N1: additions may insert bytes, but every original byte outside
        // changed fields must survive, including lexical choices the DOM loses.
        const std::string lexical {
            "\xef\xbb\xbf<?xml version='1.0'?>\n<systemList>\n\t<!-- my systems -->\n\n"
            "\t<system>\n\t\t<name>test</name> <!-- trailing note -->\n"
            "\t\t<fullname>Test &amp; &#233;</fullname>\n"
            "\t\t<path>%ROMPATH%/test</path>\n\t\t<extension>.rom</extension>\n"
            "\t\t<command label='Original'>PLACEHOLDER %ROM%</command>\n"
            "\t\t<opaque quote='a > b'><![CDATA[<not-a-tag/>]]><?user keep?></opaque>\n"
            "\t</system>\n\n\n"
            "\t<system><name>compact</name><fullname>Compact</fullname><path>p</path>"
            "<extension>.u</extension><command>c %ROM%</command></system>\n"
            "  <system>\n      <name>mixed</name>\n      <fullname>Mixed</fullname>\n"
            "      <path>q</path>\n      <extension>.v</extension>\n"
            "      <command>c %ROM%</command>\n  </system>\n</systemList>\n"};
        for (int variant {0}; variant < 4; ++variant) {
            const auto directory = root + "/bytes-" + std::to_string(variant);
            require(mkdir(directory.c_str(), 0700) == 0, "byte-preservation scratch");
            std::string original {lexical};
            if (variant == 1)
                for (size_t i {0}; (i = original.find('\n', i)) != std::string::npos; i += 2)
                    original.insert(i, 1, '\r');
            if (variant == 2) {
                original.erase(0, 3); // No BOM, deliberately mixed line endings.
                original.insert(original.find("\n\n"), 1, '\r');
            }
            if (variant == 3) {
                original.erase(0, 3);
                const auto begin = original.find("\t<system>");
                const auto end = original.find("</system>", begin) + 9;
                auto compact = original.substr(begin, end - begin);
                for (auto position = compact.find_first_of("\t\n"); position != std::string::npos;
                     position = compact.find_first_of("\t\n"))
                    compact.erase(position, 1);
                original.replace(begin, end - begin, compact);
            }
            const std::string originalRules {
                "\xef\xbb\xbf<?xml version='1.0'?>\r\n<ruleList>\r\n\r\n"
                "  <!-- user rules -->\r\n  <emulator name='User'><rule type='androidpackage'>"
                "<entry>org.user/Activity</entry></rule></emulator> <!-- inline -->\r\n"
                "\r\n</ruleList>\r\n"};
            put(directory + "/es_systems.xml", original);
            put(directory + "/es_find_rules.xml", originalRules);
            EmulatorManagerConfig bytes {directory, bundle, bundledRules};
            const auto id = bytes.add("test", "Bytes", "org.bytes/Activity", collisionProfile,
                                      variant == 2 ? ".zip" : "", true);
            bytes.save();
            auto expected = original;
            if (variant == 2)
                expected.replace(expected.find(".rom</extension>"), 4, ".rom .zip");
            const auto insertion = expected.find("</system>");
            const auto actual = read(directory + "/es_systems.xml");
            const auto added = actual.size() - expected.size();
            require(actual.substr(0, insertion) == expected.substr(0, insertion) &&
                        actual.substr(insertion + added) == expected.substr(insertion) &&
                        actual.substr(insertion, added).find("ES-DE-Plus addition") !=
                            std::string::npos,
                    "BOM, blank lines, inline comments, quotes/entities, compact and mixed-indent "
                    "systems retain exact untouched bytes");
            const auto actualRules = read(directory + "/es_find_rules.xml");
            const auto ruleInsertion = originalRules.find("</ruleList>");
            require(
                actualRules.substr(0, ruleInsertion) == originalRules.substr(0, ruleInsertion) &&
                    actualRules.substr(ruleInsertion + actualRules.size() - originalRules.size()) ==
                        originalRules.substr(ruleInsertion),
                "rules retain declaration, BOM, CRLF, blank lines, compact rules and inline "
                "comment bytes");
            EmulatorManagerConfig readback {directory, bundle, bundledRules};
            require(readback.system("test").commands.back().addition == id,
                    "byte-preserving upstream readback");
            pugi::xml_document owned;
            require(owned.load_buffer(actual.data(), actual.size(), pugi::parse_full),
                    "owned parse");
            auto system = owned.child("systemList").child("system");
            auto command = system.find_child_by_attribute("command", "label", "Bytes");
            auto marker = command.previous_sibling();
            std::string removed = actual;
            for (const auto& token :
                 {std::string("<!--") + marker.value() + "-->",
                  actual.substr(actual.find("<command label=\"Bytes\""),
                                actual.find("</command>", actual.find("<command label=\"Bytes\"")) +
                                    10 - actual.find("<command label=\"Bytes\""))}) {
                const auto position = removed.find(token);
                require(position != std::string::npos, "owned lexical boundary");
                removed.erase(position, token.size());
            }
            readback.remove("test", id);
            readback.save();
            require(read(directory + "/es_systems.xml") == removed &&
                        tree(removed) == tree(expected) &&
                        read(directory + "/es_find_rules.xml") == actualRules,
                    "removal deletes only exact owned tokens; all other bytes and semantic tree "
                    "retained");
            EmulatorManagerConfig unchanged {directory, bundle, bundledRules};
            unchanged.save();
            require(read(directory + "/es_systems.xml") == removed &&
                        read(directory + "/es_find_rules.xml") == actualRules,
                    "no-op save retains exact bytes");
            const auto gamelist = directory + "/gamelist.xml";
            const std::string selections {
                "\xef\xbb\xbf<?xml version='1.0'?>\r\n<gameList>\r\n\r\n"
                "  <game><path>one.zip</path><altemulator>Removed</altemulator></game> <!-- keep "
                "-->\r\n"
                "\t<game><path>two.zip</path><altemulator>Other</altemulator></game>\r\n</"
                "gameList>\r\n"};
            put(gamelist, selections);
            EmulatorManagerConfig::clearSelections(gamelist, {"Removed"});
            auto repaired = selections;
            repaired.erase(repaired.find("Removed"), 7);
            require(read(gamelist) == repaired,
                    "selection repair changes only selected text bytes");
        }
        const std::string profileText {
            "%EMULATOR_X% %ACTION%=android.intent.action.VIEW %MIMETYPE%=application/zip "
            "%EXTRA_ROM%=%ROM% %EXTRAARRAY_paths%=one,two %EXTRAINTEGER_slot%=2 "
            "%EXTRABOOL_boot%=true %ACTIVITY_CLEAR_TOP%"};
        auto profile = EmulatorLaunchProfile::fromCommand(profileText);
        require(profile.action == "android.intent.action.VIEW" &&
                    profile.mime == "application/zip" && profile.extras.size() == 4 &&
                    profile.clearTop,
                "structured profile parse");
        auto roundtrip = EmulatorLaunchProfile::fromCommand(profile.command("NEW"));
        require(roundtrip.command("NEW") == profile.command("NEW"),
                "structured profile grammar roundtrip");
        profile.rom("%ROMPROVIDER%", "");
        refused([&] { profile.rom("%ROMPROVIDER%", "ROM"); });
        profile.extras.push_back({"EXTRAINTEGER", "overflow", "2147483648"});
        refused([&] { profile.command("NEW"); });
        refused([&] { EmulatorLaunchProfile::fromCommand("%EMULATOR_X% %UNKNOWN%=value"); });
        std::cout
            << "PASS: precedence, unlabeled policy, partial failure/retry, preservation, "
               "ownership, external edit, malformed/ambiguous refusal, snapshot/refresh/reset; "
               "exact removal/ambiguous-label refusal; shared stable rules; "
               "declaration/indent/CRLF readback; mixed/opaque/CDATA/xml:space preservation; "
               "exact-byte BOM/layout preservation\n";
    }
    catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
