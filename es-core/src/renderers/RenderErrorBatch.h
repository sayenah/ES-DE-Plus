//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  RenderErrorBatch.h
//
//  Written for ES-DE-Plus. Scope debug error reads around a drawing batch while
//  retaining the recorded GL errors and ordinary per-command checks elsewhere.
//

#ifndef ES_CORE_RENDERERS_RENDER_ERROR_BATCH_H
#define ES_CORE_RENDERERS_RENDER_ERROR_BATCH_H

#include "renderers/Renderer.h"

#include <cassert>

class RenderErrorBatch
{
public:
    explicit RenderErrorBatch(Renderer& renderer, const char* label)
        : mRenderer {&renderer}
        , mLabel {label}
    {
        mRenderer->beginErrorBatch();
    }
    ~RenderErrorBatch() { finish(); }
    RenderErrorBatch(const RenderErrorBatch&) = delete;
    RenderErrorBatch& operator=(const RenderErrorBatch&) = delete;

    void finish()
    {
        auto* renderer = mRenderer;
        mRenderer = nullptr;
        if (renderer) {
            renderer->endErrorBatch(mLabel);
            mDeferred = sDeferred;
            mReads = sReads;
        }
    }
    unsigned int deferredChecks() const { return mDeferred; }
    unsigned int errorReads() const { return mReads; }

    static bool deferred()
    {
        if (!sDepth)
            return false;
        ++sDeferred;
        return true;
    }
    static void recordRead() { ++sReads; }

private:
    friend class RendererOpenGL;
    static void begin()
    {
        if (!sDepth) {
            sDeferred = 0;
            sReads = 0;
        }
        ++sDepth;
    }
    static bool end()
    {
        assert(sDepth);
        return --sDepth == 0;
    }
    inline static thread_local unsigned int sDepth {0};
    inline static thread_local unsigned int sDeferred {0};
    inline static thread_local unsigned int sReads {0};
    Renderer* mRenderer;
    const char* mLabel;
    unsigned int mDeferred {0};
    unsigned int mReads {0};
};

#endif // ES_CORE_RENDERERS_RENDER_ERROR_BATCH_H
