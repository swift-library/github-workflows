import Foundation

let output = URL(fileURLWithPath: CommandLine.arguments[1])
try """
enum GeneratedGreeting {
  static let message = "Hello, workflows!"
}
""".write(to: output, atomically: true, encoding: .utf8)
