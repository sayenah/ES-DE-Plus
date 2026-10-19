//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  TouchOverlayReset.h
//
//  Written for ES-DE-Plus. Startup acknowledgement of a private setup-session intent.
//

#ifndef ES_CORE_TOUCH_OVERLAY_RESET_H
#define ES_CORE_TOUCH_OVERLAY_RESET_H

#include <cstdio>
#include <fstream>
#include <iterator>
#include <string>

namespace TouchOverlay
{
    // The configurator atomically writes UUID + newline + selected root, separately
    // from its disposable draft. No root means the setup has not been committed.
    // apply() must persist and verify the setting before acknowledging the intent.
    template <typename Apply>
    bool consumeReset(const std::string& marker,
                      const std::string& root,
                      Apply apply,
                      bool* failed = nullptr)
    {
        if (failed)
            *failed = false;
        std::ifstream input {marker, std::ios::binary};
        std::string session;
        if (!std::getline(input, session) || session.empty())
            return false;
        const std::string selected {std::istreambuf_iterator<char> {input}, {}};
        input.close();
        if (selected.empty() || selected != root)
            return false;
        const bool consumed {apply() && std::remove(marker.c_str()) == 0};
        if (failed)
            *failed = !consumed;
        return consumed;
    }
} // namespace TouchOverlay

#endif // ES_CORE_TOUCH_OVERLAY_RESET_H
