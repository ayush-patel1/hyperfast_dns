configure_file(include/hfdns/version.hpp.in ${CMAKE_CURRENT_BINARY_DIR}/generated/hfdns/version.hpp @ONLY)

add_library(hfdns
    src/admin_server.cpp
    src/cli.cpp
    src/config.cpp
    src/duration.cpp
    src/error.cpp
    src/log.cpp
    src/net.cpp
)
target_include_directories(hfdns
    PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}/include
        ${CMAKE_CURRENT_BINARY_DIR}/generated)
target_compile_options(hfdns PRIVATE ${HFDNS_WARNINGS})
target_link_libraries(hfdns
    PUBLIC
        nlohmann_json::nlohmann_json
    PRIVATE
        yaml-cpp::yaml-cpp
        spdlog::spdlog
        hfdns_httplib
        Threads::Threads)

add_executable(hfdns-lb src/main.cpp)
target_compile_options(hfdns-lb PRIVATE ${HFDNS_WARNINGS})
target_link_libraries(hfdns-lb PRIVATE hfdns)

if(HFDNS_BUILD_TESTS)
    add_subdirectory(tests)
endif()
