// swift-tools-version: 6.1
import PackageDescription

let package = Package(
  name: "docs-multiple-targets",
  products: [
    .library(name: "GreetingKit", targets: ["Greeting-Kit"])
  ],
  traits: [
    .default(enabledTraits: ["Base"]),
    .trait(name: "Base"),
    .trait(name: "Experimental"),
  ],
  targets: [
    .target(name: "GreetingCore"),
    .target(name: "Greeting-Kit", dependencies: ["GreetingCore"]),
    .executableTarget(name: "GreetingCLI", dependencies: ["Greeting-Kit"]),
  ]
)
