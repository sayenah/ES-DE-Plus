//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  SearchFrame.cpp
//
//  Written for ES-DE-Plus. Retain an unchanged opaque search frame on the GPU.
//  All framebuffer bindings are restored; unsupported targets use normal drawing.
//
#include "renderers/RendererOpenGL.h"

bool RendererOpenGL::captureFrame(FrameCache& cache)
{
    if (getScreenRotation() != 0 || hasClipRect() || mViewport.w <= 0 || mViewport.h <= 0)
        return false;
    GLint previousRead {0}, previousDraw {0};
    GL_CHECK_ERROR(glGetIntegerv(GL_READ_FRAMEBUFFER_BINDING, &previousRead));
    GL_CHECK_ERROR(glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING, &previousDraw));
    if (!cache.framebuffer || cache.width != mViewport.w || cache.height != mViewport.h) {
        releaseFrameCache(cache);
        GLint samples {0};
        GL_CHECK_ERROR(glGetIntegerv(GL_SAMPLES, &samples));
        if (samples)
            return false;
        GLint limit {0};
        GL_CHECK_ERROR(glGetIntegerv(GL_MAX_TEXTURE_SIZE, &limit));
        if (mViewport.w > limit || mViewport.h > limit)
            return false;
        cache.texture = createTexture(0, TextureType::RGBA, false, false, false, false, mViewport.w,
                                      mViewport.h, nullptr);
        GL_CHECK_ERROR(glGenFramebuffers(1, &cache.framebuffer));
        if (!cache.texture || !cache.framebuffer) {
            releaseFrameCache(cache);
            return false;
        }
        GL_CHECK_ERROR(glBindFramebuffer(GL_DRAW_FRAMEBUFFER, cache.framebuffer));
        GL_CHECK_ERROR(glFramebufferTexture2D(GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                                              GL_TEXTURE_2D, cache.texture, 0));
        const bool complete =
            glCheckFramebufferStatus(GL_DRAW_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE;
        GL_CHECK_ERROR(glBindFramebuffer(GL_DRAW_FRAMEBUFFER, previousDraw));
        if (!complete) {
            releaseFrameCache(cache);
            return false;
        }
        cache.width = mViewport.w;
        cache.height = mViewport.h;
    }
    GL_CHECK_ERROR(glBindFramebuffer(GL_READ_FRAMEBUFFER, previousDraw));
    GL_CHECK_ERROR(glBindFramebuffer(GL_DRAW_FRAMEBUFFER, cache.framebuffer));
    const int bottom = mWindowHeight - mViewport.y - mViewport.h;
    GL_CHECK_ERROR(glBlitFramebuffer(mViewport.x, bottom, mViewport.x + mViewport.w,
                                     bottom + mViewport.h, 0, 0, cache.width, cache.height,
                                     GL_COLOR_BUFFER_BIT, GL_NEAREST));
    GL_CHECK_ERROR(glBindFramebuffer(GL_READ_FRAMEBUFFER, previousRead));
    GL_CHECK_ERROR(glBindFramebuffer(GL_DRAW_FRAMEBUFFER, previousDraw));
    return true;
}

bool RendererOpenGL::drawFrameCache(const FrameCache& cache, unsigned int background)
{
    if (!cache.framebuffer || cache.width != mViewport.w || cache.height != mViewport.h ||
        getScreenRotation() != 0 || hasClipRect())
        return false;
    // A full viewport is overwritten by the blit; preserve the normal letterbox color.
    if (mViewport.x || mViewport.y || mViewport.w != mWindowWidth || mViewport.h != mWindowHeight)
        clearBackground(background);
    GLint previousRead {0};
    GL_CHECK_ERROR(glGetIntegerv(GL_READ_FRAMEBUFFER_BINDING, &previousRead));
    GL_CHECK_ERROR(glBindFramebuffer(GL_READ_FRAMEBUFFER, cache.framebuffer));
    const int bottom = mWindowHeight - mViewport.y - mViewport.h;
    GL_CHECK_ERROR(glBlitFramebuffer(0, 0, cache.width, cache.height, mViewport.x, bottom,
                                     mViewport.x + mViewport.w, bottom + mViewport.h,
                                     GL_COLOR_BUFFER_BIT, GL_NEAREST));
    GL_CHECK_ERROR(glBindFramebuffer(GL_READ_FRAMEBUFFER, previousRead));
    return true;
}

void RendererOpenGL::releaseFrameCache(FrameCache& cache)
{
    if (cache.framebuffer)
        GL_CHECK_ERROR(glDeleteFramebuffers(1, &cache.framebuffer));
    if (cache.texture)
        destroyTexture(cache.texture);
    cache = {};
}
