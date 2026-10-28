// DaxRunner: the .NET side of recovery-bi.
//
//   validate <SemanticModel/definition>       parse the TMDL with Microsoft's own serializer and validate the model
//   port                                      print the port of the running Power BI Desktop engine
//   refresh <port>                            full refresh of the model open in Power BI Desktop
//   query <port> <queries.json> <out.json>    run each DAX query and write the result rows as JSON
//
// "validate" runs anywhere (it is what CI uses). The other commands talk to the Analysis Services
// engine that Power BI Desktop starts on localhost when a report is open, so they need Windows.

using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.AnalysisServices.AdomdClient;
using Microsoft.AnalysisServices.Tabular;

return args switch
{
    ["validate", var folder] => Validate(folder),
    ["port"] => PrintPort(),
    ["refresh", var port] => Refresh(int.Parse(port)),
    ["query", var port, var queries, var output] => Query(int.Parse(port), queries, output),
    _ => Usage(),
};

static int Usage()
{
    Console.Error.WriteLine("usage: DaxRunner validate <definition-folder> | port | refresh <port> | query <port> <queries.json> <out.json>");
    return 2;
}

static int Validate(string folder)
{
    Database db;
    try
    {
        db = TmdlSerializer.DeserializeDatabaseFromFolder(folder);
    }
    catch (Exception e) when (e.GetType().Name.StartsWith("Tmdl"))
    {
        Console.Error.WriteLine($"TMDL parse error: {e.Message}");
        return 1;
    }
    var model = db.Model;
    var errors = new List<string>();
    var result = model.Validate();
    foreach (var e in result.Errors) errors.Add(e.Message);

    var measures = model.Tables.SelectMany(t => t.Measures).ToList();
    var columns = model.Tables.SelectMany(t => t.Columns).Where(c => c.Type != ColumnType.RowNumber).ToList();
    Console.WriteLine($"compatibility {db.CompatibilityLevel}: {model.Tables.Count} tables, {columns.Count} columns, " +
                      $"{measures.Count} measures, {model.Relationships.Count} relationships");
    foreach (var e in errors) Console.Error.WriteLine($"error: {e}");
    return errors.Count == 0 ? 0 : 1;
}

static int? FindPort()
{
    // Power BI Desktop writes the port of its local engine next to the workspace it creates for each open file.
    var home = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
    var local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
    var roots = new[]
    {
        Path.Combine(home, "Microsoft", "Power BI Desktop Store App", "AnalysisServicesWorkspaces"),
        Path.Combine(local, "Microsoft", "Power BI Desktop", "AnalysisServicesWorkspaces"),
    };
    var newest = roots.Where(Directory.Exists)
        .SelectMany(r => Directory.GetFiles(r, "msmdsrv.port.txt", SearchOption.AllDirectories))
        .Select(f => new FileInfo(f)).OrderByDescending(f => f.LastWriteTimeUtc).FirstOrDefault();
    if (newest is null) return null;
    var text = File.ReadAllText(newest.FullName, System.Text.Encoding.Unicode).Trim('\0', ' ', '\r', '\n');
    return int.TryParse(text, out var port) ? port : null;
}

static int PrintPort()
{
    var port = FindPort();
    if (port is null) { Console.Error.WriteLine("Power BI Desktop is not running a model"); return 1; }
    Console.WriteLine(port);
    return 0;
}

static int Refresh(int port)
{
    using var server = new Server();
    server.Connect($"Data Source=localhost:{port}");
    var db = server.Databases[0];
    db.Model.RequestRefresh(RefreshType.Full);
    var sw = System.Diagnostics.Stopwatch.StartNew();
    db.Model.SaveChanges();
    foreach (var t in db.Model.Tables) Console.WriteLine($"{t.Name}: refreshed");
    Console.WriteLine($"refresh took {sw.Elapsed.TotalSeconds:F1} s");
    return 0;
}

static int Query(int port, string queriesPath, string outPath)
{
    var queries = JsonNode.Parse(File.ReadAllText(queriesPath))!.AsArray();
    using var conn = new AdomdConnection($"Data Source=localhost:{port}");
    conn.Open();
    var results = new JsonObject
    {
        ["engine"] = $"Power BI Desktop Analysis Services {conn.ServerVersion}",
        ["generated_utc"] = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ"),
    };
    var outQueries = new JsonObject();
    foreach (var q in queries)
    {
        var id = q!["id"]!.GetValue<string>();
        var dax = q["dax"]!.GetValue<string>();
        using var cmd = new AdomdCommand(dax, conn);
        using var reader = cmd.ExecuteReader();
        var rows = new JsonArray();
        while (reader.Read())
        {
            var row = new JsonObject();
            for (var i = 0; i < reader.FieldCount; i++)
            {
                var v = reader.GetValue(i);
                row[reader.GetName(i)] = v switch
                {
                    null or DBNull => null,
                    DateTime d => JsonValue.Create(d.ToString("yyyy-MM-dd")),
                    decimal m => JsonValue.Create(m),
                    double x => JsonValue.Create(x),
                    long l => JsonValue.Create(l),
                    int n => JsonValue.Create(n),
                    bool b => JsonValue.Create(b),
                    _ => JsonValue.Create(v.ToString()),
                };
            }
            rows.Add(row);
        }
        outQueries[id] = rows;
        Console.WriteLine($"{id}: {rows.Count} rows");
    }
    results["queries"] = outQueries;
    File.WriteAllText(outPath, results.ToJsonString(new JsonSerializerOptions { WriteIndented = true }) + "\n");
    return 0;
}
