//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  SearchArtwork.h
//
//  Written for ES-DE-Plus. Visible-only artwork requests with no frontend pointers on the worker.
//

#ifndef ES_APP_SEARCH_ARTWORK_H
#define ES_APP_SEARCH_ARTWORK_H

#include <condition_variable>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

class SearchArtwork
{
public:
    static constexpr size_t MAX_DIMENSION {384};
    struct Request {
        std::string id;
        std::string gamePath;
        std::string system;
        std::string romRoot;
        std::string mediaRoot;
    };
    struct Pixels {
        std::vector<unsigned char> rgba;
        size_t width {0};
        size_t height {0};
    };
    SearchArtwork();
    ~SearchArtwork();
    void request(std::vector<Request> visible);
    std::shared_ptr<const Pixels> get(const std::string& id);

private:
    void work();
    std::mutex mMutex;
    std::condition_variable mWake;
    bool mExit {false};
    std::vector<Request> mVisible;
    // Cache paths (including misses) for this screen's lifetime. Pixel data is bounded to
    // visible rows; textures belong to the GUI thread and are never touched here.
    std::map<std::string, std::string> mPaths;
    std::map<std::string, std::shared_ptr<const Pixels>> mReady;
    std::thread mWorker;
};
#endif
