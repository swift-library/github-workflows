/// A greeting used by the command-line fixture.
public func greeting() -> String {
  "Hello, workflows!"
}

#if os(iOS)
  #error("Apple build fixture")
#endif
