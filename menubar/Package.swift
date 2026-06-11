// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "HomeServicesMenuBar",
    platforms: [
        .macOS(.v13)
    ],
    products: [
        .executable(name: "HomeServicesMenuBar", targets: ["HomeServicesMenuBar"])
    ],
    targets: [
        .executableTarget(name: "HomeServicesMenuBar")
    ]
)
