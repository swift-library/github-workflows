/// A greeting used by the command-line fixture.
public func greeting() -> String {
  "Hello, workflows!"
}

#if !DEBUG
  #error("Release build fixture")
#endif
