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

    void normalizeXml(pugi::xml_node node)
    {
        bool container {false};
        for (auto child : node.children())
            container |= child.type() == pugi::node_element || child.type() == pugi::node_comment;
        for (auto child = node.first_child(); child;) {
            const auto next = child.next_sibling();
            // Empty text and no text are semantically identical. pugixml 1.14
            // drops empty text nodes on readback, whereas newer versions retain them.
            if (child.type() == pugi::node_pcdata &&
                (std::string(child.value()).empty() ||
                 (container &&
                  std::string(child.value()).find_first_not_of(" \t\r\n") == std::string::npos)))
                node.remove_child(child);
            else
                normalizeXml(child);
            child = next;
        }
    }

    pugi::xml_node copyXml(pugi::xml_document& copy, pugi::xml_node source)
    {
        pugi::xml_node node;
        if (source.type() == pugi::node_document) {
            for (auto child : source.children())
                copy.append_copy(child);
            node = copy;
        }
        else {
            node = copy.append_copy(source);
        }
        normalizeXml(node);
        if (node.type() == pugi::node_document)
            for (auto child : node.children())
                if (child.type() == pugi::node_declaration && child.attribute("encoding"))
                    child.attribute("encoding").set_value("UTF-8");
        return node;
    }

    std::string xml(pugi::xml_node source)
    {
        pugi::xml_document copy;
        const auto node = copyXml(copy, source);
        std::ostringstream stream;
        node.print(stream, "", pugi::format_raw, pugi::encoding_utf8);
        return stream.str();
    }

    std::string formatted(pugi::xml_node source, const std::string& original)
    {
        std::string indent {"    "};
        bool found {false};
        for (size_t line = original.find('\n'); line != std::string::npos;
             line = original.find('\n', line + 1)) {
            const auto end = original.find_first_not_of(" \t", line + 1);
            if (end != std::string::npos && end > line + 1 && original[end] == '<') {
                auto candidate = original.substr(line + 1, end - line - 1);
                if (!found || candidate.size() < indent.size()) {
                    indent = candidate;
                    found = true;
                }
            }
        }
        pugi::xml_document copy;
        const auto node = copyXml(copy, source);
        std::ostringstream stream;
        node.print(stream, indent.c_str(), pugi::format_default, pugi::encoding_utf8);
        std::string output = stream.str();
        // XML parsers normalize input newlines. Retain the file's CRLF convention
        // on output where the original consistently used it, including declarations.
        if (original.find("\r\n") != std::string::npos) {
            bool crlf {true};
            for (size_t i {0}; i < original.size(); ++i)
                if (original[i] == '\n' && (i == 0 || original[i - 1] != '\r'))
                    crlf = false;
            if (crlf) {
                for (size_t i {0}; (i = output.find('\n', i)) != std::string::npos; i += 2)
                    output.insert(i, 1, '\r');
            }
        }
        pugi::xml_document readback;
        if (!readback.load_buffer(output.data(), output.size(),
                                  pugi::parse_full | pugi::parse_ws_pcdata) ||
            xml(readback) != xml(source))
            throw std::runtime_error(_("Cannot preserve the configuration while formatting XML"));
        return output;
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

    pugi::xml_node additionMarker(pugi::xml_node command)
    {
        for (auto previous = command.previous_sibling(); previous;
             previous = previous.previous_sibling()) {
            if (previous.type() == pugi::node_pcdata && words(previous.value()).empty())
                continue;
            if (previous.type() != pugi::node_comment)
                break;
            if (std::string(previous.value()).find(additionPrefix) != 0)
                continue;
            const auto fields = words(std::string(previous.value()).substr(additionPrefix.size()));
            if (fields.size() != 2)
                throw std::runtime_error(_("Invalid addition metadata"));
            return fields[1] == EmulatorManagerConfig::fingerprint(xml(command)) ?
                       previous :
                       pugi::xml_node {};
        }
        return {};
    }

    void uniqueLabels(pugi::xml_node system)
    {
        std::set<std::string> labels;
        for (auto command : system.children("command"))
            if (!labels.insert(command.attribute("label").value()).second)
                throw std::runtime_error(
                    _("Duplicate command labels: repair them before changing emulators"));
    }

    std::string baseline(pugi::xml_node node, const std::string& originalExtensions)
    {
        pugi::xml_document copy;
        auto base = copy.append_copy(node);
        for (auto command = base.child("command"); command;) {
            auto next = command.next_sibling("command");
            auto marker = additionMarker(command);
            if (marker) {
                base.remove_child(marker);
                base.remove_child(command);
            }
            command = next;
        }
        for (auto child = base.first_child(); child;) {
            const auto next = child.next_sibling();
            if (child.type() == pugi::node_comment &&
                (std::string(child.value()).find(snapshotPrefix) == 0 ||
                 std::string(child.value()).find(additionPrefix) == 0))
                base.remove_child(child);
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

    void syncDirectory(const std::string& path)
    {
        int directory = open(path.c_str(), O_RDONLY | O_DIRECTORY);
        if (directory < 0)
            throw std::runtime_error(_("Cannot sync configuration directory"));
        int synced = fsync(directory);
        close(directory);
        if (synced != 0)
            throw std::runtime_error(_("Cannot sync configuration directory"));
    }

    void replaceFile(const std::string& path,
                     const std::string& bytes,
                     const std::function<void()>& beforeRename,
                     const std::function<void()>& replaced)
    {
        std::string temporary {path + ".emulator-manager-XXXXXX"};
        int fd {mkstemp(temporary.data())};
        if (fd < 0)
            throw std::runtime_error(_("Cannot stage ") + path);
        try {
            struct stat original {
            };
            struct stat staged {
            };
            if (fstat(fd, &staged) != 0)
                throw std::runtime_error(_("Cannot inspect staged configuration"));
            if (stat(path.c_str(), &original) == 0 &&
                (original.st_mode & 0777) != (staged.st_mode & 0777) &&
                fchmod(fd, original.st_mode & 0777) != 0)
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
            replaced();
            syncDirectory(path.substr(0, path.find_last_of('/')));
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

EmulatorManagerConfig::EmulatorManagerConfig(const EmulatorManagerConfig& other)
    : mDirectory {other.mDirectory}
    , mBundledSystems {other.mBundledSystems}
    , mSystemsBytes {other.mSystemsBytes}
    , mRulesBytes {other.mRulesBytes}
    , mCheckpoint {other.mCheckpoint}
{
    mSystems.reset(other.mSystems);
    mRules.reset(other.mRules);
    mBundle.reset(other.mBundle);
    mBundleRules.reset(other.mBundleRules);
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
        auto marker = additionMarker(cmd);
        if (marker)
            addition = words(std::string(marker.value()).substr(additionPrefix.size()))[0];
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

std::vector<std::string> EmulatorManagerConfig::profileTargets(const std::string& command) const
{
    auto begin = command.find("%EMULATOR_");
    if (begin == std::string::npos)
        return {};
    auto end = command.find('%', begin + 1);
    if (end == std::string::npos)
        return {};
    auto name = command.substr(begin + 10, end - begin - 10);
    auto emulator = named(mRules.child("ruleList"), "emulator", name, true);
    if (!emulator)
        emulator = named(mBundleRules.child("ruleList"), "emulator", name, true);
    std::vector<std::string> result;
    for (auto rule : emulator.children("rule"))
        if (std::string(rule.attribute("type").value()) == "androidpackage")
            for (auto entry : rule.children("entry"))
                result.push_back(entry.text().get());
    return result;
}

pugi::xml_node EmulatorManagerConfig::editable(const std::string& name)
{
    auto node = named(mSystems.child("systemList"), "system", name);
    if (node)
        return node;
    node = mSystems.child("systemList").append_copy(effective(name));
    markSnapshot(node);
    return node;
}

void EmulatorManagerConfig::markSnapshot(pugi::xml_node node)
{
    const auto extensions = std::string(node.child("extension").text().get());
    const std::string metadata {snapshotPrefix +
                                mBundledSystems.substr(mBundledSystems.find_last_of('/') + 1) +
                                " " + fingerprint(xml(node)) + " " + baseline(node, extensions) +
                                " " + hex(extensions) + " " + fingerprint(extensions)};
    node.prepend_child(pugi::node_comment).set_value(metadata.c_str());
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
    const auto slash = component.find('/');
    // Android aliases are names, not Java classes. The GUI validates accessibility
    // with PackageManager; preserve the exact alias in upstream's package/activity grammar.
    if (slash == std::string::npos || slash + 1 == component.size() ||
        !std::regex_match(component.substr(0, slash),
                          std::regex("[A-Za-z][A-Za-z0-9_]*(\\.[A-Za-z0-9_]+)*")) ||
        std::any_of(component.begin() + slash + 1, component.end(),
                    [](unsigned char c) { return c < 0x20 || c == 0x7f; }))
        throw std::runtime_error(_("Select a valid installed package and receiving activity"));
    if (label.empty() || label.size() > 256 ||
        std::any_of(label.begin(), label.end(),
                    [](unsigned char c) { return c < 0x20 || c == 0x7f; }))
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
                _("Duplicate existing command labels: repair them before adding"));
    }
    if (labels.count(label))
        throw std::runtime_error(_("That emulator label already exists"));
    if (labels.count("") && (count != 1 || !nameUnlabelled))
        throw std::runtime_error(
            _("An unlabelled command needs an explicit label before adding alternatives"));
    auto addedExtensions = words(extensions);
    for (auto ext : addedExtensions) {
        if (ext.size() < 2 || ext[0] != '.' ||
            ext.find_first_not_of(
                ".abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-") !=
                std::string::npos)
            throw std::runtime_error(
                _("Extensions must be dot-prefixed file types separated by spaces"));
    }
    const auto key = fingerprint(name + "\n" + label + "\n" + component + "\n" + profile);
    std::string id {"ESDEPLUS_" + key};
    auto matches = [&](pugi::xml_node emulator) {
        // Compare the complete supported rule shape; comments/unknown structure
        // are left alone rather than assumed to describe an equivalent recipient.
        for (auto attribute : emulator.attributes())
            if (std::string(attribute.name()) != "name")
                return false;
        size_t rules {0};
        for (auto rule : emulator.children()) {
            if (rule.type() == pugi::node_pcdata && words(rule.value()).empty())
                continue;
            if (std::string(rule.name()) != "rule" ||
                std::string(rule.attribute("type").value()) != "androidpackage")
                return false;
            for (auto attribute : rule.attributes())
                if (std::string(attribute.name()) != "type")
                    return false;
            ++rules;
            size_t entries {0};
            for (auto entry : rule.children()) {
                if (entry.type() == pugi::node_pcdata && words(entry.value()).empty())
                    continue;
                if (std::string(entry.name()) != "entry" || entry.text().get() != component ||
                    entry.first_attribute() || !entry.first_child() ||
                    entry.first_child().type() != pugi::node_pcdata ||
                    entry.first_child().next_sibling())
                    return false;
                ++entries;
            }
            if (entries != 1)
                return false;
        }
        return rules == 1;
    };
    std::set<std::string> additionIds;
    for (auto system : mSystems.child("systemList").children("system"))
        for (auto child : system.children())
            if (child.type() == pugi::node_comment &&
                std::string(child.value()).find(additionPrefix) == 0) {
                const auto fields = words(std::string(child.value()).substr(additionPrefix.size()));
                if (fields.size() == 2)
                    additionIds.insert(fields[0]);
            }
    unsigned int suffix {0};
    while (true) {
        auto existing = named(mRules.child("ruleList"), "emulator", id, true);
        if (!existing)
            existing = named(mBundleRules.child("ruleList"), "emulator", id, true);
        if (!additionIds.count(id) && (!existing || matches(existing)))
            break;
        id = "ESDEPLUS_" + key + "_" + std::to_string(++suffix);
    }
    // Ownership IDs stay distinct even when several additions share one equivalent
    // find rule. Reuse does not edit or prune any existing (possibly user-owned) rule.
    std::string ruleId {id};
    bool reuse {false};
    for (auto rule : mRules.child("ruleList").children("emulator"))
        if (std::string(rule.attribute("name").value()).find("ESDEPLUS_") == 0 && matches(rule)) {
            ruleId = rule.attribute("name").value();
            reuse = true;
            break;
        }
    if (!reuse) {
        auto existing = named(mBundleRules.child("ruleList"), "emulator", ruleId, true);
        reuse = existing && matches(existing);
    }
    const std::string command = replaceEmulator(profile, ruleId);
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
    if (!reuse) {
        auto rule = mRules.child("ruleList").append_child("emulator");
        rule.append_attribute("name").set_value(id.c_str());
        rule.append_child("rule").append_attribute("type").set_value("androidpackage");
        rule.child("rule").append_child("entry").text().set(component.c_str());
    }
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
    auto node = named(mSystems.child("systemList"), "system", name);
    uniqueLabels(node);
    pugi::xml_node owned;
    pugi::xml_node marker;
    for (auto command : node.children("command")) {
        auto candidate = additionMarker(command);
        if (candidate && !addition.empty() &&
            words(std::string(candidate.value()).substr(additionPrefix.size()))[0] == addition) {
            if (owned)
                throw std::runtime_error(_("Ambiguous manager metadata"));
            owned = command;
            marker = candidate;
        }
    }
    if (!owned)
        throw std::runtime_error(_("This addition has been edited or is no longer manager-owned; "
                                   "preserve it and repair manually"));
    // Node identity, never label lookup: intervening user comments and all other
    // commands survive. An identical rule is reused if this addition is added again.
    node.remove_child(marker);
    node.remove_child(owned);
}

void EmulatorManagerConfig::reset(const std::string& name)
{
    auto node = named(mSystems.child("systemList"), "system", name);
    if (!node)
        return;
    auto source = named(mBundle.child("systemList"), "system", name);
    if (!source)
        throw std::runtime_error(_("This custom system has no bundled definition"));
    if (mSystems.child("loadExclusive")) {
        // Keep the directive and the system's reachability. There is no transparent
        // inheritance under loadExclusive, so explicit reset retains a fresh snapshot.
        auto fresh = node.parent().insert_copy_before(source, node);
        markSnapshot(fresh);
    }
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
        auto marker = additionMarker(cmd);
        if (marker) {
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
    const std::string metadata {
        snapshotPrefix + mBundledSystems.substr(mBundledSystems.find_last_of('/') + 1) + " " +
        fingerprint(xml(source)) + " " + baseline(fresh, originalExtensions) + " " +
        hex(originalExtensions) + " " + fingerprint(extensionValue)};
    fresh.prepend_child(pugi::node_comment).set_value(metadata.c_str());
    fresh.child("extension").text().set(extensionValue.c_str());
    parent.remove_child(node);
}

void EmulatorManagerConfig::clearSelections(const std::string& path,
                                            const std::vector<std::string>& labels)
{
    if (path.empty())
        return;
    const auto original = read(path, true);
    if (original.empty())
        return;
    pugi::xml_document doc;
    if (!doc.load_buffer(original.data(), original.size(),
                         pugi::parse_full | pugi::parse_ws_pcdata) ||
        !doc.child("gameList") || doc.child("gameList").next_sibling("gameList"))
        throw std::runtime_error(_("Cannot inspect emulator selections in gamelist.xml"));
    auto matching = [&](const std::string& value) {
        return !value.empty() && std::find(labels.begin(), labels.end(), value) != labels.end();
    };
    bool changed {false};
    auto alternative = doc.child("alternativeEmulator") ?
                           doc.child("alternativeEmulator") :
                           doc.child("gameList").child("alternativeEmulator");
    if (matching(alternative.child("label").text().get())) {
        alternative.child("label").text().set("");
        changed = true;
    }
    for (auto game : doc.child("gameList").children("game"))
        if (matching(game.child("altemulator").text().get())) {
            game.child("altemulator").text().set("");
            changed = true;
        }
    if (changed)
        replaceFile(
            path, formatted(doc, original),
            [&] {
                if (read(path) != original)
                    throw std::runtime_error(
                        _("gamelist.xml changed during selection repair; retry"));
            },
            [] {});
    else
        syncDirectory(path.substr(0, path.find_last_of('/')));
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
                _("Configuration changed outside the manager; reopen it before applying"));
    };
    const auto systemsBytes = formatted(mSystems, mSystemsBytes);
    const auto rulesBytes = formatted(mRules, mRulesBytes);
    unchanged();
    // Also retry a directory sync if the previous attempt renamed a file but
    // could not confirm its durability. Never publish commands before that succeeds.
    syncDirectory(mDirectory);
    if (mCheckpoint)
        mCheckpoint(0);
    if (rulesBytes != mRulesBytes) {
        replaceFile(rulesPath, rulesBytes, unchanged, [&] { mRulesBytes = rulesBytes; });
    }
    if (mCheckpoint)
        mCheckpoint(1);
    // Rules are durable before any command can reference them. A partial save
    // leaves harmless unused rules, and this same draft can retry without duplication.
    if (systemsBytes != mSystemsBytes) {
        replaceFile(systemsPath, systemsBytes, unchanged, [&] { mSystemsBytes = systemsBytes; });
    }
    if (mCheckpoint)
        mCheckpoint(2);
}
