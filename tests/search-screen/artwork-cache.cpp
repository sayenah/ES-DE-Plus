//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  artwork-cache.cpp
//
//  Written for ES-DE-Plus. Exercises actual UI artwork methods while a worker owns the lock.
//

#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <cstdlib>
#include <future>
#include <map>
#include <memory>
#include <mutex>
#include <set>
#include <string>
#include <thread>
#include <vector>

// Counted storage seams; the request/pump/get methods below are extracted from production.
class SearchArtwork
{
public:
    struct Request {
        std::string id;
    };
    struct Pixels {
    };
    void request(std::vector<Request> visible);
    void pump();
    std::shared_ptr<const Pixels> get(const std::string& id);
    std::mutex mMutex;
    std::condition_variable mWake;
    std::vector<Request> mVisible;
    std::vector<Request> mPending;
    bool mPendingDirty {false};
    std::map<std::string, std::shared_ptr<const Pixels>> mReady;
};

#include "artwork-get.inc"
#include "artwork-pump.inc"
#include "artwork-request.inc"

namespace
{
    int checks {0};
    void require(bool condition, const char* reason)
    {
        ++checks;
        if (!condition) {
            std::fprintf(stderr, "FAIL: artwork cache %s\n", reason);
            std::exit(1);
        }
    }
} // namespace

int main()
{
    SearchArtwork cache;
    const auto pixels = std::make_shared<SearchArtwork::Pixels>();
    cache.mVisible = {{"old"}};
    cache.mReady["old"] = pixels;
    std::promise<void> locked, release;
    auto released = release.get_future();
    std::thread worker {[&] {
        std::unique_lock<std::mutex> lock {cache.mMutex};
        locked.set_value();
        released.wait();
    }};
    locked.get_future().wait();
    auto ui = std::async(std::launch::async, [&] {
        cache.request({{"obsolete"}});
        cache.request({{"latest"}});
        cache.pump();
        return !cache.get("old") && cache.mPendingDirty && cache.mPending.size() == 1 &&
               cache.mPending.front().id == "latest";
    });
    // Bound a regression's wait, then always join the worker before evaluating assertions.
    const auto status = ui.wait_for(std::chrono::seconds(2));
    release.set_value();
    worker.join();
    const bool pending = ui.get();
    require(status == std::future_status::ready,
            "UI methods finish before the worker releases its mutex");
    require(pending, "contention retains the latest visibility and does not read locked pixels");
    require(cache.mVisible.size() == 1 && cache.mVisible.front().id == "old",
            "failed publication leaves the worker's current request intact");
    cache.pump();
    require(!cache.mPendingDirty && cache.mVisible.size() == 1 &&
                cache.mVisible.front().id == "latest",
            "the next frame publishes the latest pending request");
    require(cache.mReady.empty(), "publication releases pixels for rows no longer visible");
    cache.mReady["latest"] = pixels;
    cache.request({{"latest"}});
    require(cache.get("latest") == pixels, "a still-visible image retains its decoded pixels");
    require(!cache.get("missing"), "an unavailable visible image remains an optional miss");
    cache.request({});
    require(cache.mVisible.empty() && cache.mReady.empty() && !cache.mPendingDirty,
            "empty visibility retires decoded pixels without leaving stale pending work");
    cache.pump();
    require(cache.mVisible.empty(), "a clean pump does not resurrect an earlier request");
    std::printf("PASS: %d production artwork contention checks\n", checks);
}
