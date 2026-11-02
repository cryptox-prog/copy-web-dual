#include <curl/curl.h>
#include <chrono>
#include <iostream>
#include <stdexcept>
#include <string>
#include <thread>

static size_t receive(char* data, size_t size, size_t count, void* output) {
    static_cast<std::string*>(output)->append(data, size * count);
    return size * count;
}

// Returns the browser's exact UTF-8 text. Throws on transport failure or timeout.
std::string relay_images(const std::string& server, int count, char** paths,
                         std::chrono::seconds timeout = std::chrono::seconds(3600)) {
    CURL* curl = curl_easy_init();
    if (!curl) throw std::runtime_error("Could not initialize curl");
    curl_mime* form = curl_mime_init(curl);
    try {
        for (int i = 0; i < count; ++i) {
            auto* part = curl_mime_addpart(form);
            curl_mime_name(part, "images");
            if (curl_mime_filedata(part, paths[i]) != CURLE_OK)
                throw std::runtime_error(std::string("Cannot read image: ") + paths[i]);
        }
        std::string response;
        curl_easy_setopt(curl, CURLOPT_URL, (server + "/api/requests").c_str());
        curl_easy_setopt(curl, CURLOPT_MIMEPOST, form);
        curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, receive);
        curl_easy_setopt(curl, CURLOPT_WRITEDATA, &response);
        curl_easy_setopt(curl, CURLOPT_CONNECTTIMEOUT, 10L);
        curl_easy_setopt(curl, CURLOPT_TIMEOUT, 120L);
        curl_easy_setopt(curl, CURLOPT_NOSIGNAL, 1L);
        auto perform = [&]() {
            response.clear();
            auto result = curl_easy_perform(curl);
            if (result != CURLE_OK) throw std::runtime_error(curl_easy_strerror(result));
            long status = 0;
            curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &status);
            return status;
        };
        if (perform() != 201) throw std::runtime_error("Upload rejected: " + response);
        // The server emits a generated hex identifier as its first JSON field.
        auto key = response.find("\"id\": \"");
        if (key == std::string::npos) throw std::runtime_error("Invalid server response");
        std::string id = response.substr(key + 7, 32);
        if (id.size() != 32 || id.find_first_not_of("0123456789abcdef") != std::string::npos)
            throw std::runtime_error("Invalid request ID");
        std::cerr << "Uploaded request " << id << ". Waiting for a reply at " << server << "\n";
        curl_easy_setopt(curl, CURLOPT_MIMEPOST, nullptr);
        curl_easy_setopt(curl, CURLOPT_HTTPGET, 1L);
        curl_easy_setopt(curl, CURLOPT_URL, (server + "/api/requests/" + id + "/reply").c_str());
        curl_easy_setopt(curl, CURLOPT_TIMEOUT, 30L);
        const auto deadline = std::chrono::steady_clock::now() + timeout;
        while (std::chrono::steady_clock::now() < deadline) {
            long status = perform();
            if (status == 200) {
                curl_mime_free(form); curl_easy_cleanup(curl); return response;
            }
            if (status != 202) throw std::runtime_error("Reply request failed: " + response);
            std::this_thread::sleep_for(std::chrono::seconds(1));
        }
        throw std::runtime_error("Timed out waiting for reply; request remains on the server: " + id);
    } catch (...) {
        curl_mime_free(form); curl_easy_cleanup(curl); throw;
    }
}

int main(int argc, char** argv) {
    if (argc < 3) {
        std::cerr << "Usage: " << argv[0] << " http://localhost:8080 image.png [more-images...]\n";
        return 1;
    }
    curl_global_init(CURL_GLOBAL_DEFAULT);
    int status = 0;
    try {
        std::string server = argv[1];
        while (!server.empty() && server.back() == '/') server.pop_back();
        std::cout << relay_images(server, argc - 2, argv + 2) << '\n';
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n'; status = 1;
    }
    curl_global_cleanup();
    return status;
}
