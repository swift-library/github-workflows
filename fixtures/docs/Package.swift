// swift-tools-version: 6.0
import PackageDescription

let package = Package(
  name: "fixture-package",
  platforms: [.macOS(.v13), .iOS(.v16)],
  products: [
    .library(name: "Fixture", targets: ["Fixture"]),
    .executable(name: "fixture-cli", targets: ["fixture-cli"]),
  ],
  targets: [
    .target(name: "Fixture"),
    .executableTarget(name: "fixture-cli", dependencies: ["Fixture"]),
    .testTarget(name: "FixtureTests", dependencies: ["Fixture"]),
  ]
)
