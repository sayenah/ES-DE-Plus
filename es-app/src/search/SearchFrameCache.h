//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  SearchFrameCache.h
//
//  Written for ES-DE-Plus. Cache only settled search frames between edits.
//  Query frames always execute the normal measured drawing path.
//
#ifndef ES_APP_SEARCH_FRAME_CACHE_H
#define ES_APP_SEARCH_FRAME_CACHE_H

#include "renderers/Renderer.h"
#include "resources/ResourceManager.h"

#include <memory>

class SearchFrameCache final : public IReloadable
{
public:
    static std::shared_ptr<SearchFrameCache> create()
    {
        auto value = std::make_shared<SearchFrameCache>();
        ResourceManager::getInstance().addReloadable(value);
        return value;
    }
    SearchFrameCache() = default;
    SearchFrameCache(const SearchFrameCache&) = delete;
    SearchFrameCache& operator=(const SearchFrameCache&) = delete;
    ~SearchFrameCache() { reset(); }
    bool valid() const { return mValid; }
    unsigned int savedFrames() const { return mSaved; }
    unsigned int reusedFrames() const { return mReused; }
    bool unavailable() const { return mDisabled; }
    void invalidate() { mValid = false; }
    void reset()
    {
        Renderer::getInstance()->releaseFrameCache(mFrame);
        mValid = false;
        mDisabled = false;
        mSaved = mReused = 0;
    }
    bool draw(unsigned int background = 0)
    {
        if (!mValid || mDisabled || !Renderer::getInstance()->drawFrameCache(mFrame, background))
            return false;
        ++mReused;
        return true;
    }
    void capture()
    {
        if (mDisabled)
            return;
        mValid = Renderer::getInstance()->captureFrame(mFrame);
        mDisabled = !mValid;
        if (mValid)
            ++mSaved;
    }
    void unload(ResourceManager&) override { reset(); }
    void reload(ResourceManager&) override {}

private:
    Renderer::FrameCache mFrame;
    bool mValid {false}, mDisabled {false};
    unsigned int mSaved {0}, mReused {0};
};

#endif // ES_APP_SEARCH_FRAME_CACHE_H
