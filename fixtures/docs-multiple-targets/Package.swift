// swift-tools-version: 6.0
import PackageDescription

let package = Package(
  name: "docs-multiple-targets",
  products: [
    .library(name: "GreetingKit", targets: ["Greeting-Kit"])
  ],
  targets: [
    .target(name: "GreetingCore"),
    .target(name: "Greeting-Kit", dependencies: ["GreetingCore"]),
  ]
)
