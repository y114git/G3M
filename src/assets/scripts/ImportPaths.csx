#load "SharedPaths.csx"

using System;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using UndertaleModLib;
using UndertaleModLib.Models;

EnsureDataLoaded();

void PrintLine(string s) => Console.WriteLine(s);

var ctx = PrepareImportContext();
string inputRoot = ctx.InputRoot;
string pathsIn = Path.Combine(inputRoot, "Paths");

if (!Directory.Exists(pathsIn))
{
    PrintLine("[ImportPaths] No Paths directory found, skipping import.");
    return;
}

string[] pathFiles = Directory.GetFiles(pathsIn, "*.json");
if (pathFiles.Length == 0)
{
    PrintLine("[ImportPaths] No path JSON files found, skipping import.");
    return;
}

PrintLine($"[ImportPaths] Found {pathFiles.Length} path file(s) to import.");

SetProgressBar(null, "Importing Paths", 0, pathFiles.Length);
StartProgressBarUpdater();

SyncBinding("Paths, Strings", true);

foreach (string pathFile in pathFiles)
{
    try
    {
        string jsonContent = File.ReadAllText(pathFile, Encoding.UTF8);
        string pathName = Path.GetFileNameWithoutExtension(pathFile);
        
        JsonDocument jsonDoc = JsonDocument.Parse(jsonContent);
        JsonElement root = jsonDoc.RootElement;
        
        UndertalePath path = Data.Paths?.ByName(pathName);
        bool isNew = false;
        
        if (path == null)
        {
            
            path = new UndertalePath();
            path.Name = Data.Strings.MakeString(pathName);
            path.Points = new UndertaleSimpleList<UndertalePath.PathPoint>();
            path.IsSmooth = false;
            path.IsClosed = false;
            path.Precision = 4;
            isNew = true;
            PrintLine($"[ImportPaths] Creating NEW path: {pathName}");
        }

        if (root.TryGetProperty("isSmooth", out JsonElement isSmoothElm))
        {
            path.IsSmooth = isSmoothElm.GetBoolean();
        }

        if (root.TryGetProperty("isClosed", out JsonElement isClosedElm))
        {
            path.IsClosed = isClosedElm.GetBoolean();
        }

        if (root.TryGetProperty("precision", out JsonElement precisionElm))
        {
            path.Precision = (uint)precisionElm.GetInt32();
        }

        if (root.TryGetProperty("points", out JsonElement pointsElm) && pointsElm.ValueKind == JsonValueKind.Array)
        {
            path.Points.Clear();
            foreach (JsonElement pointElm in pointsElm.EnumerateArray())
            {
                var point = new UndertalePath.PathPoint();
                if (pointElm.TryGetProperty("x", out JsonElement xElm))
                {
                    point.X = (float)xElm.GetDouble();
                }
                if (pointElm.TryGetProperty("y", out JsonElement yElm))
                {
                    point.Y = (float)yElm.GetDouble();
                }
                if (pointElm.TryGetProperty("speed", out JsonElement speedElm))
                {
                    point.Speed = (float)speedElm.GetDouble();
                }
                path.Points.Add(point);
            }
        }

        if (isNew)
        {
            Data.Paths.Add(path);
            PrintLine($"[ImportPaths] Created new path: {pathName}");
        }
        else
        {
            PrintLine($"[ImportPaths] Updated path: {pathName}");
        }
        jsonDoc.Dispose();
        IncrementProgress();
    }
    catch (Exception ex)
    {
        PrintLine($"[ImportPaths] Error importing path {Path.GetFileName(pathFile)}: {ex.Message}");
        IncrementProgress();
    }
}

await StopProgressBarUpdater();
HideProgressBar();
PrintLine("[ImportPaths] Done.");

