// swift-tools-version: 6.0
import PackageDescription

let package = Package(
  name: "apple-plugin",
  platforms: [.macOS(.v13), .iOS(.v16)],
  products: [
    .library(name: "PluginFixture", targets: ["PluginFixture"])
  ],
  targets: [
    .target(name: "PluginFixture", plugins: ["GenerateGreeting"]),
    .plugin(
      name: "GenerateGreeting",
      capability: .buildTool(),
      dependencies: ["GreetingGenerator"]
    ),
    .executableTarget(name: "GreetingGenerator"),
  ]
)
