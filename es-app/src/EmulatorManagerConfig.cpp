//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  EmulatorManagerConfig.cpp
//
//  Written for ES-DE-Plus from the documented upstream XML grammar.
//

#include "EmulatorManagerConfig.h"

#include "utils/LocalizationUtil.h"

#include <algorithm>
#include <cerrno>
#include <cstdint>
#include <fcntl.h>
#include <fstream>
#include <iomanip>
#include <regex>
#include <set>
#include <sstream>
#include <stdexcept>
#include <sys/stat.h>
#include <unistd.h>

namespace
{
    const std::string snapshotPrefix {"ES-DE-Plus snapshot "};
    const std::string additionPrefix {"ES-DE-Plus addition "};

    std::string read(const std::string& path, bool optional = false)
    {
        struct stat info {
        };
        if (lstat(path.c_str(), &info) != 0) {
            if (optional && errno == ENOENT)
                return "";
            throw std::runtime_error(_("Cannot inspect ") + path);
        }
        if (!S_ISREG(info.st_mode))
            throw std::runtime_error(_("Not a regular file: ") + path);
        std::ifstream stream {path, std::ios::binary};
        if (!stream)
            throw std::runtime_error(_("Cannot read ") + path);
        std::string bytes {std::istreambuf_iterator<char>(stream), {}};
        if (stream.bad() || bytes.empty())
            throw std::runtime_error(_("Cannot finish reading ") + path);
        return bytes;
    }

    std::string xml(pugi::xml_node node)
    {
        std::ostringstream stream;
        node.print(stream, "", pugi::format_raw, pugi::encoding_utf8);
        return stream.str();
    }

    std::vector<std::string> words(const std::string& value)
    {
        std::istringstream stream {value};
        std::vector<std::string> result;
        for (std::string word; stream >> word;)
            result.push_back(word);
        return result;
    }

    std::string hex(const std::string& value)
    {
        std::ostringstream out;
        for (unsigned char c : value)
            out << std::hex << std::setw(2) << std::setfill('0') << static_cast<unsigned int>(c);
        return out.str().empty() ? "-" : out.str();
    }

    std::string unhex(const std::string& value)
    {
        if (value == "-")
            return "";
        if (value.size() % 2 != 0 ||
            value.find_first_not_of("0123456789abcdef") != std::string::npos)
            throw std::runtime_error(_("Invalid snapshot metadata"));
        std::string result;
        for (size_t i {0}; i < value.size(); i += 2)
            result += static_cast<char>(std::stoi(value.substr(i, 2), nullptr, 16));
        return result;
    }

    pugi::xml_node named(pugi::xml_node root,
                         const char* tag,
                         const std::string& name,
                         bool attribute = false)
    {
        pugi::xml_node result;
        for (auto entry : root.children(tag)) {
            const std::string value {attribute ? entry.attribute("name").value() :
                                                 entry.child("name").text().get()};
            if (value == name) {
                if (result)
                    throw std::runtime_error(_("Ambiguous duplicate entry: ") + name);
                result = entry;
            }
        }
        return result;
    }

    void load(pugi::xml_document& doc, const std::string& bytes, const char* root)
    {
        if (bytes.empty()) {
            doc.append_child(root);
            return;
        }
        const auto result =
            doc.load_buffer(bytes.data(), bytes.size(), pugi::parse_full | pugi::parse_ws_pcdata);
        if (!result || !doc.child(root))
            throw std::runtime_error(_("Invalid configuration") + ": " + root +
                                     " XML: " + result.description());
        if (doc.child(root).next_sibling(root))
            throw std::runtime_error(_("Ambiguous XML root"));
        // pugixml deliberately supports upstream's top-level loadExclusive sibling.
        for (auto node : doc.children()) {
            if (node.type() == pugi::node_doctype)
                throw std::runtime_error(_("DTD configuration is not supported by the manager"));
            if (node.type() == pugi::node_element && std::string(node.name()) != root &&
                std::string(node.name()) != "loadExclusive")
                throw std::runtime_error(_("Unexpected top-level XML element"));
        }
        std::set<std::string> names;
        for (auto node :
             doc.child(root).children(std::string(root) == "systemList" ? "system" : "emulator")) {
            std::string name {std::string(root) == "systemList" ? node.child("name").text().get() :
                                                                  node.attribute("name").value()};
            if (name.empty() || !names.insert(name).second)
                throw std::runtime_error(_("Missing or duplicate entry name"));
        }
    }

    pugi::xml_node comment(pugi::xml_node node, const std::string& prefix)
    {
        pugi::xml_node result;
        for (auto child : node.children()) {
            if (child.type() == pugi::node_comment &&
                std::string(child.value()).find(prefix) == 0) {
                if (result)
                    throw std::runtime_error(_("Ambiguous manager metadata"));
                result = child;
            }
        }
        return result;
    }

    std::string baseline(pugi::xml_node node, const std::string& originalExtensions)
    {
        pugi::xml_document copy;
        auto base = copy.append_copy(node);
        for (auto child = base.first_child(); child;) {
            auto next = child.next_sibling();
            if (child.type() == pugi::node_comment &&
                (std::string(child.value()).find(snapshotPrefix) == 0 ||
                 std::string(child.value()).find(additionPrefix) == 0)) {
                if (std::string(child.value()).find(additionPrefix) == 0 &&
                    std::string(next.name()) == "command") {
                    auto after = next.next_sibling();
                    base.remove_child(next);
                    next = after;
                }
                base.remove_child(child);
            }
            child = next;
        }
        base.child("extension").text().set(originalExtensions.c_str());
        return EmulatorManagerConfig::fingerprint(xml(base));
    }

    std::vector<std::string> snapshot(pugi::xml_node node)
    {
        auto metadata = comment(node, snapshotPrefix);
        if (!metadata)
            return {};
        auto fields = words(std::string(metadata.value()).substr(snapshotPrefix.size()));
        if (fields.size() != 5)
            throw std::runtime_error(_("Invalid snapshot metadata"));
        return fields;
    }

    void replaceFile(const std::string& path,
                     const std::string& bytes,
                     const std::function<void()>& beforeRename)
    {
        std::string temporary {path + ".emulator-manager-XXXXXX"};
        int fd {mkstemp(temporary.data())};
        if (fd < 0)
            throw std::runtime_error(_("Cannot stage ") + path);
        try {
            struct stat original {
            };
            if (stat(path.c_str(), &original) == 0 && fchmod(fd, original.st_mode & 0777) != 0)
                throw std::runtime_error(_("Cannot preserve file permissions"));
            size_t offset {0};
            while (offset < bytes.size()) {
                const auto count = write(fd, bytes.data() + offset, bytes.size() - offset);
                if (count < 0 && errno == EINTR)
                    continue;
                if (count <= 0)
                    throw std::runtime_error(_("Cannot stage complete configuration"));
                offset += count;
            }
            if (fsync(fd) != 0)
                throw std::runtime_error(_("Cannot sync configuration"));
            const int closed = close(fd);
            fd = -1;
            if (closed != 0)
                throw std::runtime_error(_("Cannot close configuration"));
            beforeRename();
            if (rename(temporary.c_str(), path.c_str()) != 0)
                throw std::runtime_error(_("Cannot replace ") + path);
            const auto slash = path.find_last_of('/');
            int directory = open(path.substr(0, slash).c_str(), O_RDONLY | O_DIRECTORY);
            if (directory < 0)
                throw std::runtime_error(_("Cannot sync configuration directory"));
            int synced = fsync(directory);
            close(directory);
            if (synced != 0)
                throw std::runtime_error(_("Cannot sync configuration directory"));
        }
        catch (...) {
            if (fd >= 0)
                close(fd);
            unlink(temporary.c_str());
            throw;
        }
    }
} // namespace

EmulatorManagerConfig::EmulatorManagerConfig(const std::string& directory,
                                             const std::string& bundledSystems,
                                             const std::string& bundledRules)
    : mDirectory {directory}
    , mBundledSystems {bundledSystems}
    , mSystemsBytes {read(directory + "/es_systems.xml", true)}
    , mRulesBytes {read(directory + "/es_find_rules.xml", true)}
{
    load(mSystems, mSystemsBytes, "systemList");
    load(mRules, mRulesBytes, "ruleList");
    load(mBundle, read(bundledSystems), "systemList");
    load(mBundleRules, read(bundledRules), "ruleList");
}

std::string EmulatorManagerConfig::fingerprint(const std::string& bytes)
{
    // Change detection, not authentication. Exact file bytes are compared before every write.
    uint64_t hash {14695981039346656037ULL};
    for (unsigned char c : bytes) {
        hash ^= c;
        hash *= 1099511628211ULL;
    }
    std::ostringstream stream;
    stream << std::hex << hash;
    return stream.str();
}

pugi::xml_node EmulatorManagerConfig::effective(const std::string& name) const
{
    auto node = named(mSystems.child("systemList"), "system", name);
    if (!node && !mSystems.child("loadExclusive"))
        node = named(mBundle.child("systemList"), "system", name);
    if (!node)
        throw std::runtime_error(_("System no longer exists in effective configuration"));
    return node;
}

std::vector<EmulatorManagerConfig::System> EmulatorManagerConfig::systems() const
{
    std::set<std::string> names;
    for (auto node : mSystems.child("systemList").children("system"))
        names.insert(node.child("name").text().get());
    if (!mSystems.child("loadExclusive"))
        for (auto node : mBundle.child("systemList").children("system"))
            names.insert(node.child("name").text().get());
    std::vector<System> result;
    for (const auto& name : names)
        result.push_back(system(name));
    return result;
}

EmulatorManagerConfig::System EmulatorManagerConfig::system(const std::string& name) const
{
    auto node = effective(name);
    System result {name,
                   node.child("fullname").text().get(),
                   node.child("path").text().get(),
                   node.child("extension").text().get(),
                   {},
                   static_cast<bool>(named(mSystems.child("systemList"), "system", name)),
                   false};
    for (auto cmd : node.children("command")) {
        std::string addition;
        auto previous = cmd.previous_sibling();
        if (previous.type() == pugi::node_comment &&
            std::string(previous.value()).find(additionPrefix) == 0) {
            auto fields = words(std::string(previous.value()).substr(additionPrefix.size()));
            if (fields.size() != 2)
                throw std::runtime_error(_("Invalid addition metadata"));
            if (fields[1] == fingerprint(xml(cmd)))
                addition = fields[0];
        }
        result.commands.push_back({cmd.attribute("label").value(), cmd.text().get(), addition});
    }
    auto fields = snapshot(node);
    if (!fields.empty()) {
        auto source = named(mBundle.child("systemList"), "system", name);
        result.stale = !source ||
                       fields[0] != mBundledSystems.substr(mBundledSystems.find_last_of('/') + 1) ||
                       fields[1] != fingerprint(xml(source));
    }
    return result;
}

pugi::xml_node EmulatorManagerConfig::editable(const std::string& name)
{
    auto node = named(mSystems.child("systemList"), "system", name);
    if (node)
        return node;
    node = mSystems.child("systemList").append_copy(effective(name));
    const auto extensions = std::string(node.child("extension").text().get());
    const std::string metadata {snapshotPrefix +
                                mBundledSystems.substr(mBundledSystems.find_last_of('/') + 1) +
                                " " + fingerprint(xml(node)) + " " + baseline(node, extensions) +
                                " " + hex(extensions) + " " + fingerprint(extensions)};
    node.prepend_child(pugi::node_comment).set_value(metadata.c_str());
    return node;
}

std::string EmulatorManagerConfig::replaceEmulator(const std::string& profile,
                                                   const std::string& rule)
{
    const auto start = profile.find("%EMULATOR_");
    const auto end = start == std::string::npos ? start : profile.find('%', start + 1);
    if (start == std::string::npos || end == std::string::npos ||
        profile.find("%EMULATOR_", end + 1) != std::string::npos)
        throw std::runtime_error(_("Profile must contain exactly one emulator find rule"));
    return profile.substr(0, start) + "%EMULATOR_" + rule + "%" + profile.substr(end + 1);
}

std::string EmulatorManagerConfig::add(const std::string& name,
                                       const std::string& label,
                                       const std::string& component,
                                       const std::string& profile,
                                       const std::string& extensions,
                                       bool nameUnlabelled)
{
    if (!std::regex_match(
            component,
            std::regex("[A-Za-z][A-Za-z0-9_]*(\\.[A-Za-z0-9_]+)+/[A-Za-z_][A-Za-z0-9_.$]*")))
        throw std::runtime_error(_("Select a valid installed package and receiving activity"));
    if (label.empty() || label.size() > 256 || label.find_first_of("\r\n\t") != std::string::npos)
        throw std::runtime_error(_("Enter a unique emulator label"));
    auto source = effective(name);
    for (const char* required : {"name", "fullname", "path", "extension"}) {
        if (!source.child(required) || source.child(required).next_sibling(required) ||
            std::string(source.child(required).text().get()).empty())
            throw std::runtime_error(
                _("The target system has missing or ambiguous required fields"));
    }
    std::set<std::string> labels;
    size_t count {0};
    for (auto cmd : source.children("command")) {
        ++count;
        std::string value {cmd.attribute("label").value()};
        if (!labels.insert(value).second)
            throw std::runtime_error(
                "Duplicate existing command labels: repair them before adding");
    }
    if (labels.count(label))
        throw std::runtime_error(_("That emulator label already exists"));
    if (labels.count("") && (count != 1 || !nameUnlabelled))
        throw std::runtime_error(
            "An unlabelled command needs an explicit label before adding alternatives");
    auto addedExtensions = words(extensions);
    for (auto ext : addedExtensions) {
        if (ext.size() < 2 || ext[0] != '.' ||
            ext.find_first_not_of(
                ".abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-") !=
                std::string::npos)
            throw std::runtime_error(
                "Extensions must be dot-prefixed file types separated by spaces");
    }
    const auto key = fingerprint(name + "\n" + label + "\n" + component + "\n" + profile);
    std::string id {"ESDEPLUS_" + key};
    auto collision = [&](const std::string& value) {
        return named(mRules.child("ruleList"), "emulator", value, true) ||
               named(mBundleRules.child("ruleList"), "emulator", value, true);
    };
    unsigned int suffix {0};
    while (collision(id))
        id = "ESDEPLUS_" + key + "_" + std::to_string(++suffix);
    const std::string command = replaceEmulator(profile, id);
    auto node = editable(name);
    if (labels.count("")) {
        std::string original {_("Original emulator")};
        while (labels.count(original) || original == label)
            original += _(" (original)");
        node.child("command").append_attribute("label").set_value(original.c_str());
        auto fields = snapshot(node);
        if (!fields.empty()) {
            fields[2] = baseline(node, unhex(fields[3]));
            comment(node, snapshotPrefix)
                .set_value((snapshotPrefix + fields[0] + " " + fields[1] + " " + fields[2] + " " +
                            fields[3] + " " + fields[4])
                               .c_str());
        }
    }
    auto rule = mRules.child("ruleList").append_child("emulator");
    rule.append_attribute("name").set_value(id.c_str());
    rule.append_child("rule").append_attribute("type").set_value("androidpackage");
    rule.child("rule").append_child("entry").text().set(component.c_str());
    auto cmd = node.append_child("command");
    cmd.append_attribute("label").set_value(label.c_str());
    cmd.text().set(command.c_str());
    node.insert_child_before(pugi::node_comment, cmd)
        .set_value((additionPrefix + id + " " + fingerprint(xml(cmd))).c_str());
    std::string extensionValue {node.child("extension").text().get()};
    auto existing = words(extensionValue);
    for (auto ext : addedExtensions) {
        if (std::find(existing.begin(), existing.end(), ext) == existing.end()) {
            extensionValue += " " + ext;
            existing.push_back(ext);
        }
    }
    node.child("extension").text().set(extensionValue.c_str());
    auto fields = snapshot(node);
    if (!fields.empty()) {
        fields[4] = fingerprint(extensionValue);
        comment(node, snapshotPrefix)
            .set_value((snapshotPrefix + fields[0] + " " + fields[1] + " " + fields[2] + " " +
                        fields[3] + " " + fields[4])
                           .c_str());
    }
    return id;
}

void EmulatorManagerConfig::remove(const std::string& name, const std::string& addition)
{
    auto current = system(name);
    for (const auto& cmd : current.commands) {
        if (cmd.addition == addition && !addition.empty()) {
            auto node = editable(name);
            for (auto entry : node.children("command")) {
                if (std::string(entry.attribute("label").value()) == cmd.label) {
                    node.remove_child(entry.previous_sibling());
                    node.remove_child(entry);
                    // Keep the rule: later hand edits may reference it. An unused rule is safe.
                    // Extensions remain available to other commands and existing games.
                    return;
                }
            }
        }
    }
    throw std::runtime_error(_("This addition has been edited or is no longer manager-owned; "
                               "preserve it and repair manually"));
}

void EmulatorManagerConfig::reset(const std::string& name)
{
    auto node = named(mSystems.child("systemList"), "system", name);
    if (!node)
        return;
    if (mSystems.child("loadExclusive"))
        throw std::runtime_error(_("Reset would hide this system under loadExclusive; remove that "
                                   "directive manually first"));
    if (!named(mBundle.child("systemList"), "system", name))
        throw std::runtime_error(_("This custom system has no bundled definition"));
    mSystems.child("systemList").remove_child(node);
}

void EmulatorManagerConfig::refresh(const std::string& name)
{
    auto node = editable(name);
    auto fields = snapshot(node);
    if (fields.empty() || baseline(node, unhex(fields[3])) != fields[2] ||
        fingerprint(node.child("extension").text().get()) != fields[4])
        throw std::runtime_error(_("Hand-edited snapshot: refresh refused; preserve it or "
                                   "explicitly reset the whole override"));
    auto source = named(mBundle.child("systemList"), "system", name);
    if (!source)
        throw std::runtime_error(_("Bundled system no longer exists"));
    pugi::xml_document additions;
    auto retained = additions.append_child("system");
    for (auto cmd : node.children("command")) {
        auto marker = cmd.previous_sibling();
        if (marker.type() == pugi::node_comment &&
            std::string(marker.value()).find(additionPrefix) == 0) {
            auto parts = words(std::string(marker.value()).substr(additionPrefix.size()));
            if (parts.size() != 2 || parts[1] != fingerprint(xml(cmd)))
                throw std::runtime_error(_("Hand-edited addition: refresh refused"));
            retained.append_copy(marker);
            retained.append_copy(cmd);
        }
    }
    const std::string oldExtensions {node.child("extension").text().get()};
    auto parent = node.parent();
    auto fresh = parent.insert_copy_before(source, node);
    // Existing accepted extensions are retained even if the new bundle drops them.
    auto extensions = words(fresh.child("extension").text().get());
    std::string extensionValue {fresh.child("extension").text().get()};
    for (const auto& ext : words(oldExtensions))
        if (std::find(extensions.begin(), extensions.end(), ext) == extensions.end()) {
            extensions.push_back(ext);
            extensionValue += " " + ext;
        }
    if (retained.child("command") && !fresh.child("command").attribute("label")) {
        if (fresh.child("command").next_sibling("command")) {
            parent.remove_child(fresh);
            throw std::runtime_error(
                _("New bundled commands have ambiguous labels; refresh refused"));
        }
        std::string label {_("Original emulator")};
        bool collision {true};
        while (collision) {
            collision = false;
            for (auto cmd : retained.children("command"))
                if (label == cmd.attribute("label").value())
                    collision = true;
            if (collision)
                label += _(" (original)");
        }
        fresh.child("command").append_attribute("label").set_value(label.c_str());
    }
    for (auto child : retained.children()) {
        if (std::string(child.name()) == "command") {
            for (auto cmd : fresh.children("command"))
                if (std::string(cmd.attribute("label").value()) ==
                    child.attribute("label").value()) {
                    parent.remove_child(fresh);
                    throw std::runtime_error(
                        _("New bundled command collides with a retained label"));
                }
        }
        fresh.append_copy(child);
    }
    const std::string originalExtensions {source.child("extension").text().get()};
    fresh.prepend_child(pugi::node_comment)
        .set_value((snapshotPrefix + mBundledSystems.substr(mBundledSystems.find_last_of('/') + 1) +
                    " " + fingerprint(xml(source)) + " " + baseline(fresh, originalExtensions) +
                    " " + hex(originalExtensions) + " " + fingerprint(extensionValue))
                       .c_str());
    fresh.child("extension").text().set(extensionValue.c_str());
    parent.remove_child(node);
}

void EmulatorManagerConfig::verifyCurrent() const
{
    if (read(mDirectory + "/es_systems.xml", true) != mSystemsBytes ||
        read(mDirectory + "/es_find_rules.xml", true) != mRulesBytes)
        throw std::runtime_error(
            _("Configuration changed outside the manager; reopen it before applying"));
}

void EmulatorManagerConfig::save()
{
    const std::string systemsPath {mDirectory + "/es_systems.xml"};
    const std::string rulesPath {mDirectory + "/es_find_rules.xml"};
    auto unchanged = [&] {
        if (read(systemsPath, true) != mSystemsBytes || read(rulesPath, true) != mRulesBytes)
            throw std::runtime_error(
                "Configuration changed outside the manager; reopen it before applying");
    };
    const auto systemsBytes = xml(mSystems);
    const auto rulesBytes = xml(mRules);
    unchanged();
    if (mCheckpoint)
        mCheckpoint(0);
    if (rulesBytes != mRulesBytes) {
        replaceFile(rulesPath, rulesBytes, unchanged);
        mRulesBytes = rulesBytes;
    }
    if (mCheckpoint)
        mCheckpoint(1);
    // Rules are durable before any command can reference them. A partial save
    // leaves harmless unused rules, and this same draft can retry without duplication.
    if (systemsBytes != mSystemsBytes) {
        replaceFile(systemsPath, systemsBytes, unchanged);
        mSystemsBytes = systemsBytes;
    }
    if (mCheckpoint)
        mCheckpoint(2);
}
