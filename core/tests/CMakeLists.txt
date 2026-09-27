add_executable(hfdns_unit_tests
    admin_server_test.cpp
    cli_test.cpp
    config_test.cpp
    duration_test.cpp
    log_test.cpp
    net_test.cpp
)
target_compile_options(hfdns_unit_tests PRIVATE ${HFDNS_WARNINGS})
target_compile_definitions(hfdns_unit_tests PRIVATE
    HFDNS_REPO_CONFIG_DIR="${PROJECT_SOURCE_DIR}/config")
target_link_libraries(hfdns_unit_tests PRIVATE hfdns hfdns_httplib GTest::gtest GTest::gtest_main)

include(GoogleTest)
gtest_discover_tests(hfdns_unit_tests DISCOVERY_TIMEOUT 30)
