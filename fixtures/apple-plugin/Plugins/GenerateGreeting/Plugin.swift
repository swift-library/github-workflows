import PackagePlugin

@main
struct GenerateGreeting: BuildToolPlugin {
  func createBuildCommands(context: PluginContext, target: Target) async throws -> [Command] {
    let tool = try context.tool(named: "GreetingGenerator")
    let output = context.pluginWorkDirectoryURL.appending(path: "GeneratedGreeting.swift")
    return [
      .buildCommand(
        displayName: "Generate greeting",
        executable: tool.url,
        arguments: [output.path],
        outputFiles: [output]
      )
    ]
  }
}
