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
#include <stdexcept>
#include <sys/stat.h>

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
                    read(systems).find("<unknown a=\"b\">keep</unknown>") != std::string::npos &&
                    read(systems).find("loadExclusive") != std::string::npos &&
                    read(systems).find("private=\"keep\"") != std::string::npos,
                "custom preservation");
        after.remove("test", id);
        after.save();
        require(EmulatorManagerConfig(root, bundle, bundledRules).system("test").commands.size() ==
                    1,
                "remove only addition");
        refused([&] { after.reset("test"); });
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
               "ownership, external edit, malformed/ambiguous refusal, snapshot/refresh/reset\n";
    }
    catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
