import GreetingCore

/// Creates the default greeting.
public func greeting() -> Greeting {
  Greeting(text: "Hello, workflows!")
}

extension Greeting {
  /// The greeting in uppercase.
  public var shout: String {
    text.uppercased()
  }
}
