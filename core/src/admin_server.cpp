#include "hfdns/admin_server.hpp"

#include <atomic>
#include <format>
#include <thread>

#include <httplib.h>
#include <nlohmann/json.hpp>

#include "hfdns/log.hpp"

namespace hfdns {

struct AdminServer::Impl {
    Options options;
    httplib::Server server;
    std::thread thread;
    std::atomic<std::uint16_t> bound_port{0};
    std::chrono::steady_clock::time_point started_at;
};

AdminServer::AdminServer(Options options) : impl_(std::make_unique<Impl>()) {
    impl_->options = std::move(options);
}

AdminServer::~AdminServer() {
    stop();
}

Status AdminServer::start() {
    auto& impl = *impl_;
    impl.started_at = std::chrono::steady_clock::now();

    impl.server.Get("/healthz", [&impl](const httplib::Request&, httplib::Response& res) {
        const auto uptime =
            std::chrono::duration<double>(std::chrono::steady_clock::now() - impl.started_at);
        const nlohmann::json body = {
            {"status", "ok"},
            {"version", impl.options.version},
            {"uptime_seconds", uptime.count()},
        };
        res.set_content(body.dump(), "application/json");
    });
    impl.server.set_error_handler([](const httplib::Request&, httplib::Response& res) {
        if (res.body.empty()) {
            res.set_content(std::format(R"({{"error":"http {}"}})", res.status),
                            "application/json");
        }
    });

    // httplib's default options add SO_REUSEPORT, which would let a second
    // instance silently share this port. Keep only SO_REUSEADDR (fast restart).
    impl.server.set_socket_options([](socket_t sock) {
        const int yes = 1;
        setsockopt(sock, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));
    });

    const auto host = impl.options.address.to_string();
    int port = 0;
    if (impl.options.port == 0) {
        port = impl.server.bind_to_any_port(host);
    } else if (impl.server.bind_to_port(host, impl.options.port)) {
        port = impl.options.port;
    }
    if (port <= 0) {
        return make_error(ErrorCode::NetworkError,
                          std::format("admin server cannot bind {}:{}", host, impl.options.port));
    }
    impl.bound_port.store(static_cast<std::uint16_t>(port));
    impl.thread = std::thread([&impl] { impl.server.listen_after_bind(); });
    // listen_after_bind() sets its running flag on entry; a stop() issued before
    // that point would be lost and join() would hang forever.
    impl.server.wait_until_ready();
    log::info("admin_started", {{"address", host}, {"port", port}});
    return {};
}

void AdminServer::stop() {
    if (!impl_ || !impl_->thread.joinable()) {
        return;
    }
    impl_->server.stop();
    impl_->thread.join();
    log::info("admin_stopped");
}

std::uint16_t AdminServer::port() const noexcept {
    return impl_->bound_port.load();
}

}  // namespace hfdns
