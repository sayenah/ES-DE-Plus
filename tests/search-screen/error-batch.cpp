//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  error-batch.cpp
//
//  Written for ES-DE-Plus. Execute production debug error scopes, backend methods
//  and GL checks with counted commands and injected recorded flags.
//

#include "Log.h"
#include <cassert>
#include <cstdlib>
#include <deque>
#include <iostream>
#include <stdexcept>
#include <thread>
#include <type_traits>
#include <vector>

namespace
{
    int checks {0};
    thread_local unsigned int reads {0}, commands {0};
    thread_local std::deque<unsigned int> errors;
    thread_local std::vector<std::string> messages;
    void require(bool condition)
    {
        if (!condition)
            std::abort();
        ++checks;
    }
    using GLenum = unsigned int;
#if !defined(NDEBUG)
    constexpr GLenum GL_NO_ERROR {0};
    GLenum glGetError()
    {
        ++reads;
        if (errors.empty())
            return GL_NO_ERROR;
        const auto error = errors.front();
        errors.pop_front();
        return error;
    }
#endif
    void command() { ++commands; }
} // namespace
Log::~Log() { messages.push_back(mOutStringStream.str()); }
std::ostringstream& Log::get(LogLevel) { return mOutStringStream; }
LogLevel Log::getReportingLevel() { return LogDebug; }

class Renderer
{
public:
    virtual ~Renderer() = default;
    virtual void beginErrorBatch() = 0;
    virtual void endErrorBatch(const char*) = 0;
};
#include "error-batch.inc"
#include "error-check.inc"
class RendererOpenGL : public Renderer
{
public:
    void beginErrorBatch() override;
    void endErrorBatch(const char* label) override;
};
#include "error-backend.inc"

int main()
{
    static_assert(!std::is_copy_constructible_v<RenderErrorBatch>);
    static_assert(!std::is_copy_assignable_v<RenderErrorBatch>);
    RendererOpenGL renderer;
    for (int i = 0; i < 100; ++i)
        GL_CHECK_ERROR(command());
    require(commands == 100);
#if !defined(NDEBUG)
    require(reads == 100);
#else
    require(reads == 0);
#endif
    reads = 0;
    {
        RenderErrorBatch batch {renderer, "Search drawing"};
        for (int i = 0; i < 100; ++i)
            GL_CHECK_ERROR(command());
        require(reads == 0 && commands == 200);
        {
            RenderErrorBatch nested {renderer, "Nested drawing"};
            GL_CHECK_ERROR(command());
        }
        require(reads == 0 && commands == 201);
#if !defined(NDEBUG)
        // Independent recorded flags must both be reported, followed by GL_NO_ERROR.
        errors.push_back(0x500);
        errors.push_back(0x501);
#endif
        batch.finish();
#if !defined(NDEBUG)
        require(reads == 3 && batch.errorReads() == 3 && batch.deferredChecks() == 101);
        require(messages.size() == 2 && errors.empty());
        require(messages[0].find("Search drawing") != std::string::npos);
        require(messages[0].find("0x500") != std::string::npos);
        require(messages[1].find("0x501") != std::string::npos);
#if defined(USE_OPENGLES)
        require(messages[0].find("OpenGL ES error") != std::string::npos);
#else
        require(messages[0].find("OpenGL error") != std::string::npos);
#endif
#else
        require(reads == 0 && batch.errorReads() == 0 && batch.deferredChecks() == 0);
#endif
        const auto finishedReads = reads;
        batch.finish();
        require(reads == finishedReads);
    }
    const auto before = reads;
    try {
        RenderErrorBatch batch {renderer, "Unwinding"};
        GL_CHECK_ERROR(command());
        throw std::runtime_error("test");
    }
    catch (const std::runtime_error&) {
    }
    GL_CHECK_ERROR(command());
#if !defined(NDEBUG)
    require(reads == before + 2);
#else
    require(reads == before);
#endif
    // A batch on one thread must not suppress checks in another GL context thread.
    bool isolated {false};
    {
        RenderErrorBatch batch {renderer, "Main thread"};
        std::thread other {[&] {
            GL_CHECK_ERROR(command());
#if !defined(NDEBUG)
            isolated = reads == 1 && commands == 1;
#else
            isolated = reads == 0 && commands == 1;
#endif
        }};
        other.join();
        require(isolated);
    }
    reads = 0;
    {
        RenderErrorBatch batch {renderer, "Clean batch"};
        for (int i = 0; i < 100; ++i)
            GL_CHECK_ERROR(command());
        batch.finish();
#if !defined(NDEBUG)
        require(reads == 1 && batch.errorReads() == 1 && batch.deferredChecks() == 100);
#else
        require(reads == 0 && batch.errorReads() == 0 && batch.deferredChecks() == 0);
#endif
    }
    std::cout << "PASS: " << checks << " production GL error batch checks\n";
}
