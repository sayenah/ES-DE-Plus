//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  SearchArtwork.cpp
//
//  Written for ES-DE-Plus. Async media lookup/decoding; reuses upstream ImageIO.
//

#include "search/SearchArtwork.h"

#include "ImageIO.h"
#include "utils/FileSystemUtil.h"
#include "utils/StringUtil.h"

#include <algorithm>
#include <filesystem>
#include <fstream>
#include <set>

SearchArtwork::SearchArtwork()
    : mWorker {&SearchArtwork::work, this}
{
}

SearchArtwork::~SearchArtwork()
{
    {
        std::lock_guard<std::mutex> lock {mMutex};
        mExit = true;
    }
    mWake.notify_one();
    mWorker.join();
}

void SearchArtwork::request(std::vector<Request> visible)
{
    {
        std::lock_guard<std::mutex> lock {mMutex};
        std::set<std::string> ids;
        for (const auto& request : visible)
            ids.insert(request.id);
        for (auto it = mReady.begin(); it != mReady.end();) {
            if (!ids.count(it->first))
                it = mReady.erase(it);
            else
                ++it;
        }
        mVisible = std::move(visible);
    }
    mWake.notify_one();
}

std::shared_ptr<const SearchArtwork::Pixels> SearchArtwork::get(const std::string& id)
{
    std::lock_guard<std::mutex> lock {mMutex};
    const auto it = mReady.find(id);
    return it == mReady.end() ? nullptr : it->second;
}

void SearchArtwork::work()
{
    std::unique_lock<std::mutex> lock {mMutex};
    while (!mExit) {
        const auto next = std::find_if(mVisible.begin(), mVisible.end(),
                                       [&](const Request& r) { return !mReady.count(r.id); });
        if (next == mVisible.end()) {
            mWake.wait(lock);
            continue;
        }
        const auto request = *next;
        lock.unlock();
        auto pixels = std::make_shared<Pixels>();
        auto path = mPaths.find(request.id);
        if (path == mPaths.end()) {
            std::string found;
            const auto folders = Utils::String::replace(
                Utils::FileSystem::getParent(request.gamePath), request.romRoot, "");
            // getStem checks whether the ROM is a directory. Keep even that stat here.
            const auto stem = Utils::FileSystem::getStem(request.gamePath);
            for (const auto& directory : {"covers", "miximages", "screenshots", "titlescreens"}) {
                const auto base =
                    request.mediaRoot + request.system + "/" + directory + folders + "/" + stem;
                for (const auto& extension : {".png", ".jpg", ".webp"}) {
                    const std::string candidate = base + extension;
                    std::ifstream stream(std::filesystem::u8path(candidate), std::ios::binary);
                    if (stream.good()) {
                        found = candidate;
                        break;
                    }
                }
                if (!found.empty())
                    break;
            }
            path = mPaths.emplace(request.id, std::move(found)).first;
        }
        if (!path->second.empty()) {
            std::ifstream stream(std::filesystem::u8path(path->second),
                                 std::ios::binary | std::ios::ate);
            const auto length = stream.tellg();
            if (length > 0 && length <= 32 * 1024 * 1024) {
                std::vector<unsigned char> encoded(static_cast<size_t>(length));
                stream.seekg(0);
                if (stream.read(reinterpret_cast<char*>(encoded.data()), length)) {
                    size_t width {0}, height {0};
                    auto decoded = ImageIO::loadFromMemoryRGBA32(encoded.data(), encoded.size(),
                                                                 width, height);
                    if (width && height && decoded.size() == width * height * 4) {
                        // Bound each upload to TV thumbnail size; decoding and resampling stay
                        // off the input/render thread even for very large downloaded covers.
                        const double scale = std::min(1.0, static_cast<double>(MAX_DIMENSION) /
                                                               std::max(width, height));
                        pixels->width = std::max<size_t>(1, width * scale);
                        pixels->height = std::max<size_t>(1, height * scale);
                        pixels->rgba.resize(pixels->width * pixels->height * 4);
                        for (size_t y {0}; y < pixels->height; ++y)
                            for (size_t x {0}; x < pixels->width; ++x) {
                                const size_t source = ((y * height / pixels->height) * width +
                                                       x * width / pixels->width) *
                                                      4;
                                std::copy_n(decoded.data() + source, 4,
                                            pixels->rgba.data() + (y * pixels->width + x) * 4);
                            }
                    }
                }
            }
        }
        lock.lock();
        if (std::any_of(mVisible.begin(), mVisible.end(),
                        [&](const Request& r) { return r.id == request.id; }))
            mReady[request.id] = std::move(pixels);
    }
}
