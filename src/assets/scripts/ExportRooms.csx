

using System;
using System.IO;
using System.Text;
using System.Linq;
using System.Collections.Generic;
using System.Reflection;
using UndertaleModLib;
using UndertaleModLib.Models;

void PrintLine(string s) => Console.WriteLine(s);
bool DEBUG = Environment.GetEnvironmentVariable("DELTAHUB_DEBUG") == "1";
void DebugLog(string s) { if (DEBUG) PrintLine($"[DEBUG] {s}"); }

string SafeName(string name)
{
    var invalid = Path.GetInvalidFileNameChars();
    var sb = new StringBuilder(name.Length);
    foreach (var ch in name) sb.Append(invalid.Contains(ch) ? '_' : ch);
    return sb.ToString();
}

string ReadAllTextSafe(string path)
{
    try { return File.ReadAllText(path).Trim(); } catch { return null; }
}

object GetProp(object obj, string name)
    => obj?.GetType().GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.IgnoreCase)?.GetValue(obj);

EnsureDataLoaded();


string deltahubRoot = null;
{
    var probe = new DirectoryInfo(Directory.GetCurrentDirectory());
    while (probe != null)
    {
        if (Directory.Exists(Path.Combine(probe.FullName, "output"))) { deltahubRoot = probe.FullName; break; }
        probe = probe.Parent;
    }
    if (deltahubRoot == null) throw new ScriptException("DELTAHUB root not found (no /output ancestor).");
}


string chapterNo = ReadAllTextSafe(Path.Combine(deltahubRoot, "output", "Cache", "running", "chapterNumber.txt"));
string modNo     = ReadAllTextSafe(Path.Combine(deltahubRoot, "output", "Cache", "running", "modNumbersCache.txt"));
if (string.IsNullOrWhiteSpace(chapterNo) || string.IsNullOrWhiteSpace(modNo))
    throw new ScriptException("chapterNumber/modNumbersCache missing in /output/Cache/running/.");


string comparisonPath = null;
if (modNo != "0" && modNo != "1")
{
    int modNum = int.Parse(modNo);
    string previousModPath = Path.Combine(deltahubRoot, "output", "xDeltaCombiner", chapterNo, (modNum - 1).ToString(), "data.win");
    if (File.Exists(previousModPath))
    {
        comparisonPath = previousModPath;
    }
}
if (comparisonPath == null)
{
    comparisonPath = Path.Combine(deltahubRoot, "output", "xDeltaCombiner", chapterNo, "0", "data.win");
}


string modRoot         = Path.Combine(deltahubRoot, "output", "xDeltaCombiner", chapterNo, modNo);
string outputRoot      = Path.Combine(modRoot, "Objects");
string roomsOut        = Path.Combine(outputRoot, "Rooms");

Directory.CreateDirectory(outputRoot);
Directory.CreateDirectory(roomsOut);


UndertaleData comparison = null;
Dictionary<string, UndertaleRoom> comparisonRooms = new Dictionary<string, UndertaleRoom>();
if (File.Exists(comparisonPath))
{
    PrintLine($"[ExportRooms] Loading comparison file from: {comparisonPath}");
    using (var fs = new FileStream(comparisonPath, FileMode.Open, FileAccess.Read, FileShare.Read))
        comparison = UndertaleIO.Read(fs);
    if (comparison != null)
    {
        foreach (var room in comparison.Rooms)
        {
            if (room?.Name?.Content != null)
                comparisonRooms[room.Name.Content] = room;
        }
    }
}


void WriteJsonString(StringBuilder sb, string value)
{
    if (value == null) { sb.Append("null"); return; }
    sb.Append("\"");
    foreach (var ch in value)
    {
        if (ch == '"') sb.Append("\\\"");
        else if (ch == '\\') sb.Append("\\\\");
        else if (ch == '\n') sb.Append("\\n");
        else if (ch == '\r') sb.Append("\\r");
        else if (ch == '\t') sb.Append("\\t");
        else sb.Append(ch);
    }
    sb.Append("\"");
}

void WriteJsonBool(StringBuilder sb, bool value) => sb.Append(value ? "true" : "false");
void WriteJsonNumber(StringBuilder sb, int value) => sb.Append(value);
void WriteJsonNumber(StringBuilder sb, uint value) => sb.Append(value);
void WriteJsonNumber(StringBuilder sb, float value) => sb.Append(value.ToString("G9"));
void WriteJsonNumber(StringBuilder sb, double value) => sb.Append(value.ToString("G9"));


void ExportRoom(UndertaleRoom room, string outputPath)
{
    var sb = new StringBuilder();
    sb.AppendLine("{");
    
    
    WriteJsonString(sb, "name"); sb.Append(": "); WriteJsonString(sb, room.Name?.Content ?? ""); sb.AppendLine(",");
    WriteJsonString(sb, "width"); sb.Append(": "); WriteJsonNumber(sb, room.Width); sb.AppendLine(",");
    WriteJsonString(sb, "height"); sb.Append(": "); WriteJsonNumber(sb, room.Height); sb.AppendLine(",");
    WriteJsonString(sb, "speed"); sb.Append(": "); WriteJsonNumber(sb, room.Speed); sb.AppendLine(",");
    WriteJsonString(sb, "persistent"); sb.Append(": "); WriteJsonBool(sb, room.Persistent); sb.AppendLine(",");
    WriteJsonString(sb, "backgroundColor"); sb.Append(": "); WriteJsonNumber(sb, (int)(room.BackgroundColor & 0xFFFFFF)); sb.AppendLine(",");
    WriteJsonString(sb, "drawBackgroundColor"); sb.Append(": "); WriteJsonBool(sb, room.DrawBackgroundColor); sb.AppendLine(",");
    WriteJsonString(sb, "creationCodeId"); sb.Append(": "); WriteJsonString(sb, room.CreationCodeId?.Name?.Content); sb.AppendLine(",");
    WriteJsonString(sb, "flags"); sb.Append(": "); WriteJsonNumber(sb, (int)room.Flags); sb.AppendLine(",");
    WriteJsonString(sb, "world"); sb.Append(": "); WriteJsonBool(sb, room.World); sb.AppendLine(",");
    WriteJsonString(sb, "top"); sb.Append(": "); WriteJsonNumber(sb, room.Top); sb.AppendLine(",");
    WriteJsonString(sb, "left"); sb.Append(": "); WriteJsonNumber(sb, room.Left); sb.AppendLine(",");
    WriteJsonString(sb, "right"); sb.Append(": "); WriteJsonNumber(sb, room.Right); sb.AppendLine(",");
    WriteJsonString(sb, "bottom"); sb.Append(": "); WriteJsonNumber(sb, room.Bottom); sb.AppendLine(",");
    WriteJsonString(sb, "gravityX"); sb.Append(": "); WriteJsonNumber(sb, room.GravityX); sb.AppendLine(",");
    WriteJsonString(sb, "gravityY"); sb.Append(": "); WriteJsonNumber(sb, room.GravityY); sb.AppendLine(",");
    WriteJsonString(sb, "metersPerPixel"); sb.Append(": "); WriteJsonNumber(sb, room.MetersPerPixel); sb.AppendLine(",");
    
    
    WriteJsonString(sb, "backgrounds"); sb.Append(": [");
    bool first = true;
    foreach (var bg in room.Backgrounds)
    {
        if (!first) sb.Append(",");
        first = false;
        sb.AppendLine();
        sb.Append("    {");
        WriteJsonString(sb, "enabled"); sb.Append(": "); WriteJsonBool(sb, bg.Enabled); sb.Append(",");
        WriteJsonString(sb, "foreground"); sb.Append(": "); WriteJsonBool(sb, bg.Foreground); sb.Append(",");
        WriteJsonString(sb, "backgroundDefinition"); sb.Append(": "); WriteJsonString(sb, bg.BackgroundDefinition?.Name?.Content); sb.Append(",");
        WriteJsonString(sb, "x"); sb.Append(": "); WriteJsonNumber(sb, bg.X); sb.Append(",");
        WriteJsonString(sb, "y"); sb.Append(": "); WriteJsonNumber(sb, bg.Y); sb.Append(",");
        WriteJsonString(sb, "tiledHorizontally"); sb.Append(": "); WriteJsonBool(sb, bg.TiledHorizontally); sb.Append(",");
        WriteJsonString(sb, "tiledVertically"); sb.Append(": "); WriteJsonBool(sb, bg.TiledVertically); sb.Append(",");
        WriteJsonString(sb, "speedX"); sb.Append(": "); WriteJsonNumber(sb, bg.SpeedX); sb.Append(",");
        WriteJsonString(sb, "speedY"); sb.Append(": "); WriteJsonNumber(sb, bg.SpeedY); sb.Append(",");
        WriteJsonString(sb, "stretch"); sb.Append(": "); WriteJsonBool(sb, bg.Stretch);
        sb.Append("}");
    }
    sb.AppendLine();
    sb.AppendLine("],");
    
    
    WriteJsonString(sb, "views"); sb.Append(": [");
    first = true;
    foreach (var view in room.Views)
    {
        if (!first) sb.Append(",");
        first = false;
        sb.AppendLine();
        sb.Append("    {");
        WriteJsonString(sb, "enabled"); sb.Append(": "); WriteJsonBool(sb, view.Enabled); sb.Append(",");
        WriteJsonString(sb, "viewX"); sb.Append(": "); WriteJsonNumber(sb, view.ViewX); sb.Append(",");
        WriteJsonString(sb, "viewY"); sb.Append(": "); WriteJsonNumber(sb, view.ViewY); sb.Append(",");
        WriteJsonString(sb, "viewWidth"); sb.Append(": "); WriteJsonNumber(sb, view.ViewWidth); sb.Append(",");
        WriteJsonString(sb, "viewHeight"); sb.Append(": "); WriteJsonNumber(sb, view.ViewHeight); sb.Append(",");
        WriteJsonString(sb, "portX"); sb.Append(": "); WriteJsonNumber(sb, view.PortX); sb.Append(",");
        WriteJsonString(sb, "portY"); sb.Append(": "); WriteJsonNumber(sb, view.PortY); sb.Append(",");
        WriteJsonString(sb, "portWidth"); sb.Append(": "); WriteJsonNumber(sb, view.PortWidth); sb.Append(",");
        WriteJsonString(sb, "portHeight"); sb.Append(": "); WriteJsonNumber(sb, view.PortHeight); sb.Append(",");
        WriteJsonString(sb, "borderX"); sb.Append(": "); WriteJsonNumber(sb, view.BorderX); sb.Append(",");
        WriteJsonString(sb, "borderY"); sb.Append(": "); WriteJsonNumber(sb, view.BorderY); sb.Append(",");
        WriteJsonString(sb, "speedX"); sb.Append(": "); WriteJsonNumber(sb, view.SpeedX); sb.Append(",");
        WriteJsonString(sb, "speedY"); sb.Append(": "); WriteJsonNumber(sb, view.SpeedY); sb.Append(",");
        WriteJsonString(sb, "objectId"); sb.Append(": "); WriteJsonString(sb, view.ObjectId?.Name?.Content);
        sb.Append("}");
    }
    sb.AppendLine();
    sb.AppendLine("],");
    
    
    WriteJsonString(sb, "gameObjects"); sb.Append(": [");
    first = true;
    foreach (var obj in room.GameObjects)
    {
        if (!first) sb.Append(",");
        first = false;
        sb.AppendLine();
        sb.Append("    {");
        WriteJsonString(sb, "x"); sb.Append(": "); WriteJsonNumber(sb, obj.X); sb.Append(",");
        WriteJsonString(sb, "y"); sb.Append(": "); WriteJsonNumber(sb, obj.Y); sb.Append(",");
        WriteJsonString(sb, "objectDefinition"); sb.Append(": "); WriteJsonString(sb, obj.ObjectDefinition?.Name?.Content); sb.Append(",");
        WriteJsonString(sb, "instanceID"); sb.Append(": "); WriteJsonNumber(sb, obj.InstanceID); sb.Append(",");
        WriteJsonString(sb, "creationCode"); sb.Append(": "); WriteJsonString(sb, obj.CreationCode?.Name?.Content); sb.Append(",");
        WriteJsonString(sb, "scaleX"); sb.Append(": "); WriteJsonNumber(sb, obj.ScaleX); sb.Append(",");
        WriteJsonString(sb, "scaleY"); sb.Append(": "); WriteJsonNumber(sb, obj.ScaleY); sb.Append(",");
        WriteJsonString(sb, "color"); sb.Append(": "); WriteJsonNumber(sb, (int)obj.Color); sb.Append(",");
        WriteJsonString(sb, "rotation"); sb.Append(": "); WriteJsonNumber(sb, obj.Rotation); sb.Append(",");
        WriteJsonString(sb, "preCreateCode"); sb.Append(": "); WriteJsonString(sb, obj.PreCreateCode?.Name?.Content); sb.Append(",");
        WriteJsonString(sb, "imageSpeed"); sb.Append(": "); WriteJsonNumber(sb, obj.ImageSpeed); sb.Append(",");
        WriteJsonString(sb, "imageIndex"); sb.Append(": "); WriteJsonNumber(sb, obj.ImageIndex);
        sb.Append("}");
    }
    sb.AppendLine();
    sb.AppendLine("],");
    
    
    WriteJsonString(sb, "tiles"); sb.Append(": [");
    first = true;
    foreach (var tile in room.Tiles)
    {
        if (!first) sb.Append(",");
        first = false;
        sb.AppendLine();
        sb.Append("    {");
        WriteJsonString(sb, "spriteMode"); sb.Append(": "); WriteJsonBool(sb, tile.spriteMode); sb.Append(",");
        WriteJsonString(sb, "x"); sb.Append(": "); WriteJsonNumber(sb, tile.X); sb.Append(",");
        WriteJsonString(sb, "y"); sb.Append(": "); WriteJsonNumber(sb, tile.Y); sb.Append(",");
        WriteJsonString(sb, "backgroundDefinition"); sb.Append(": "); WriteJsonString(sb, tile.BackgroundDefinition?.Name?.Content); sb.Append(",");
        WriteJsonString(sb, "spriteDefinition"); sb.Append(": "); WriteJsonString(sb, tile.SpriteDefinition?.Name?.Content); sb.Append(",");
        WriteJsonString(sb, "sourceX"); sb.Append(": "); WriteJsonNumber(sb, tile.SourceX); sb.Append(",");
        WriteJsonString(sb, "sourceY"); sb.Append(": "); WriteJsonNumber(sb, tile.SourceY); sb.Append(",");
        WriteJsonString(sb, "width"); sb.Append(": "); WriteJsonNumber(sb, tile.Width); sb.Append(",");
        WriteJsonString(sb, "height"); sb.Append(": "); WriteJsonNumber(sb, tile.Height); sb.Append(",");
        WriteJsonString(sb, "tileDepth"); sb.Append(": "); WriteJsonNumber(sb, tile.TileDepth); sb.Append(",");
        WriteJsonString(sb, "instanceID"); sb.Append(": "); WriteJsonNumber(sb, tile.InstanceID); sb.Append(",");
        WriteJsonString(sb, "scaleX"); sb.Append(": "); WriteJsonNumber(sb, tile.ScaleX); sb.Append(",");
        WriteJsonString(sb, "scaleY"); sb.Append(": "); WriteJsonNumber(sb, tile.ScaleY); sb.Append(",");
        WriteJsonString(sb, "color"); sb.Append(": "); WriteJsonNumber(sb, (int)tile.Color);
        sb.Append("}");
    }
    sb.AppendLine();
    sb.AppendLine("],");
    
    
    WriteJsonString(sb, "layers"); sb.Append(": [");
    first = true;
    foreach (var layer in room.Layers)
    {
        if (!first) sb.Append(",");
        first = false;
        sb.AppendLine();
        sb.Append("    {");
        WriteJsonString(sb, "layerName"); sb.Append(": "); WriteJsonString(sb, layer.LayerName?.Content); sb.Append(",");
        WriteJsonString(sb, "layerId"); sb.Append(": "); WriteJsonNumber(sb, layer.LayerId); sb.Append(",");
        WriteJsonString(sb, "layerType"); sb.Append(": "); WriteJsonNumber(sb, (int)layer.LayerType); sb.Append(",");
        WriteJsonString(sb, "layerDepth"); sb.Append(": "); WriteJsonNumber(sb, layer.LayerDepth); sb.Append(",");
        WriteJsonString(sb, "xOffset"); sb.Append(": "); WriteJsonNumber(sb, layer.XOffset); sb.Append(",");
        WriteJsonString(sb, "yOffset"); sb.Append(": "); WriteJsonNumber(sb, layer.YOffset); sb.Append(",");
        WriteJsonString(sb, "hSpeed"); sb.Append(": "); WriteJsonNumber(sb, layer.HSpeed); sb.Append(",");
        WriteJsonString(sb, "vSpeed"); sb.Append(": "); WriteJsonNumber(sb, layer.VSpeed); sb.Append(",");
        WriteJsonString(sb, "isVisible"); sb.Append(": "); WriteJsonBool(sb, layer.IsVisible);
        
        
        sb.AppendLine(",");
        WriteJsonString(sb, "layerData"); sb.Append(": {}");
        
        sb.Append("}");
    }
    sb.AppendLine();
    sb.Append("]");
    
    sb.AppendLine();
    sb.Append("}");
    
    File.WriteAllText(outputPath, sb.ToString(), Encoding.UTF8);
}


int roomsNew = 0, roomsChanged = 0;

foreach (var room in Data.Rooms)
{
    if (room?.Name?.Content == null) continue;
    
    string roomName = room.Name.Content;
    bool isNew = !comparisonRooms.ContainsKey(roomName);
    bool isChanged = false;
    
    if (!isNew)
    {
        var compRoom = comparisonRooms[roomName];
        
        if (room.Width != compRoom.Width || room.Height != compRoom.Height ||
            room.Speed != compRoom.Speed || room.Persistent != compRoom.Persistent ||
            room.Backgrounds.Count != compRoom.Backgrounds.Count ||
            room.Views.Count != compRoom.Views.Count ||
            room.GameObjects.Count != compRoom.GameObjects.Count ||
            room.Tiles.Count != compRoom.Tiles.Count ||
            room.Layers.Count != compRoom.Layers.Count)
        {
            isChanged = true;
        }
    }
    
    if (isNew || isChanged)
    {
        string roomPath = Path.Combine(roomsOut, SafeName(roomName) + ".json");
        ExportRoom(room, roomPath);
        PrintLine($"[Room] {roomName}: {(isNew ? "NEW" : "CHANGED")}");
        if (isNew) roomsNew++; else roomsChanged++;
    }
}

PrintLine($"\n[ExportRooms] Summary for Mod {modNo}:");
PrintLine($"  Rooms - New: {roomsNew}, Changed: {roomsChanged}");
PrintLine("[ExportRooms] Done.");

