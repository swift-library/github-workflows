import GreetingCore

#if Base && Experimental
  /// Creates an experimental greeting.
  public func experimentalGreeting() -> Greeting {
    Greeting(text: "Experimental greeting")
  }
#endif

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
