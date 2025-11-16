



using System;
using System.IO;
using System.Text;
using System.Linq;
using System.Collections.Generic;
using System.Reflection;
using System.Security.Cryptography;
using UndertaleModLib;
using UndertaleModLib.Models;
using UndertaleModLib.Util;

void PrintLine(string s) => Console.WriteLine(s);
bool DEBUG = Environment.GetEnvironmentVariable("DELTAHUB_DEBUG") == "1";
void DebugLog(string s) { if (DEBUG) PrintLine($"[DEBUG] {s}"); }

string FixEventNameCasing(string codeName)
{
    
    var eventMappings = new Dictionary<string, string>
    {
        {"_create_", "_Create_"},
        {"_destroy_", "_Destroy_"},
        {"_step_", "_Step_"},
        {"_draw_", "_Draw_"},
        {"_alarm_", "_Alarm_"},
        {"_collision_", "_Collision_"},
        {"_other_", "_Other_"},
        {"_precreate_", "_PreCreate_"},
        {"_drawgui_", "_DrawGUI_"},
        {"_drawbegin_", "_DrawBegin_"},
        {"_drawend_", "_DrawEnd_"},
        {"_keypressed_", "_KeyPressed_"},
        {"_keyreleased_", "_KeyReleased_"}
    };

    string result = codeName;
    foreach (var mapping in eventMappings)
    {
        if (result.Contains(mapping.Key, StringComparison.OrdinalIgnoreCase))
        {
            
            int index = result.IndexOf(mapping.Key, StringComparison.OrdinalIgnoreCase);
            if (index >= 0)
            {
                result = result.Substring(0, index) + mapping.Value + result.Substring(index + mapping.Key.Length);
            }
        }
    }
    return result;
}

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
if (Data.IsYYC())
{
    PrintLine("[SmartExport] YYC build detected – code export not available.");
    return;
}


string deltahubRoot = null;
{
    var probe = new DirectoryInfo(Directory.GetCurrentDirectory());
    while (probe != null)
    {
        if (Directory.Exists(Path.Combine(probe.FullName, "output"))) { deltahubRoot = probe.FullName; break; }
        probe = probe.Parent;
    }
        
        if (deltahubRoot == null)
        {
            
            string TryRoot(string root)
            {
                if (string.IsNullOrWhiteSpace(root)) return null;
                string folder    = Path.Combine(root);
                return Directory.Exists(folder) ? folder : null;
            }

            var got = TryRoot(@Convert.ToString(Directory.GetParent(Convert.ToString(Directory.GetParent(Convert.ToString(Assembly.GetEntryAssembly().Location))))));
            if (got!=null){ deltahubRoot = got;}

        }
    
    if (deltahubRoot == null) throw new ScriptException("DELTAHUB root not found (no /output ancestor).");
}


string chapterNo = ReadAllTextSafe(Path.Combine(deltahubRoot, "output", "Cache", "running", "chapterNumber.txt"));
string modNo     = ReadAllTextSafe(Path.Combine(deltahubRoot, "output", "Cache", "running", "modNumbersCache.txt"));
if (string.IsNullOrWhiteSpace(chapterNo) || string.IsNullOrWhiteSpace(modNo))
    throw new ScriptException("chapterNumber/modNumbersCache missing in /output/Cache/running/." + Convert.ToString(Path.Combine(deltahubRoot, "output", "Cache", "running", "modNumbersCache.txt")));



string comparisonPath = null;
string customVanillaPath = Environment.GetEnvironmentVariable("SMARTEXPORT_VANILLA_PATH");
if (!string.IsNullOrEmpty(customVanillaPath) && File.Exists(customVanillaPath))
{
    comparisonPath = customVanillaPath;
    PrintLine($"[SmartExport] Using custom vanilla path from environment: {comparisonPath}");
}
else
{
    
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
}


string modRoot         = Path.Combine(deltahubRoot, "output", "xDeltaCombiner", chapterNo, modNo);
string outputRoot      = Path.Combine(modRoot, "Objects");
string codeOut         = Path.Combine(outputRoot, "CodeEntries");
string spritesOut      = Path.Combine(outputRoot, "Sprites");
string backgroundsOut  = Path.Combine(outputRoot, "Backgrounds");
string tilesetsOut     = Path.Combine(outputRoot, "Tilesets");
string newObjRoot      = Path.Combine(outputRoot, "NewObjects");
string objDefDir       = Path.Combine(newObjRoot, "ObjectDefinitions");
string objCodeDir      = Path.Combine(newObjRoot, "CodeEntries");

Directory.CreateDirectory(outputRoot);
Directory.CreateDirectory(codeOut);
Directory.CreateDirectory(spritesOut);
Directory.CreateDirectory(backgroundsOut);
Directory.CreateDirectory(tilesetsOut);


void MergeStraySpritesIntoObjects()
{
    var stray = Path.Combine(modRoot, "Sprites");
    if (!Directory.Exists(stray)) return;
    PrintLine("[SmartExport] WARNING: Found stray Sprites at mod root; moving into Objects/Sprites.");

    foreach (var dir in Directory.GetDirectories(stray, "*", SearchOption.AllDirectories))
    {
        var rel = Path.GetRelativePath(stray, dir);
        Directory.CreateDirectory(Path.Combine(spritesOut, rel));
    }
    foreach (var file in Directory.GetFiles(stray, "*", SearchOption.AllDirectories))
    {
        var rel = Path.GetRelativePath(stray, file);
        var dst = Path.Combine(spritesOut, rel);
        Directory.CreateDirectory(Path.GetDirectoryName(dst));
        if (File.Exists(dst)) File.Delete(dst);
        File.Move(file, dst);
    }
    try { Directory.Delete(stray, true); } catch { }
}


string vanillaPath = Path.Combine(deltahubRoot, "output", "xDeltaCombiner", chapterNo, "0", "data.win");


void WriteAssetOrder(string assetOrderPath)
{
    using var w = new StreamWriter(assetOrderPath, false, Encoding.UTF8);
    w.WriteLine("@@sounds@@");       foreach (var x in Data.Sounds)        if (x?.Name?.Content != null) w.WriteLine(x.Name.Content);
    w.WriteLine("@@sprites@@");      foreach (var x in Data.Sprites)       if (x?.Name?.Content != null) w.WriteLine(x.Name.Content);
    w.WriteLine("@@backgrounds@@");  foreach (var x in Data.Backgrounds)   if (x?.Name?.Content != null) w.WriteLine(x.Name.Content);
    w.WriteLine("@@paths@@");        foreach (var x in Data.Paths)         if (x?.Name?.Content != null) w.WriteLine(x.Name.Content);
    w.WriteLine("@@scripts@@");      foreach (var x in Data.Scripts)       if (x?.Name?.Content != null) w.WriteLine(x.Name.Content);
    w.WriteLine("@@fonts@@");        foreach (var x in Data.Fonts)         if (x?.Name?.Content != null) w.WriteLine(x.Name.Content);
    w.WriteLine("@@objects@@");      foreach (var x in Data.GameObjects)   if (x?.Name?.Content != null) w.WriteLine(x.Name.Content);
    w.WriteLine("@@timelines@@");    foreach (var x in Data.Timelines)     if (x?.Name?.Content != null) w.WriteLine(x.Name.Content);
    w.WriteLine("@@rooms@@");        foreach (var x in Data.Rooms)         if (x?.Name?.Content != null) w.WriteLine(x.Name.Content);
    w.Flush();
}


if (!File.Exists(comparisonPath))
{
    PrintLine($"[SmartExport] ERROR: Comparison file not found at {comparisonPath}");
    PrintLine("[SmartExport] Falling back to full export...");

    using (var worker = new TextureWorker())
    {
        
        foreach (var sprite in Data.Sprites)
        {
            if (sprite?.Name?.Content == null) continue;
            string sprDir = Path.Combine(spritesOut, sprite.Name.Content);
            Directory.CreateDirectory(sprDir);
            for (int i = 0; i < sprite.Textures.Count; i++)
            {
                var tpi = GetTpiFromFrame(sprite.Textures[i]);
                if (tpi != null) worker.ExportAsPNG(tpi, Path.Combine(sprDir, $"{SafeName(sprite.Name.Content)}_{i}.png"));
            }
        }
        
        foreach (var bg in Data.Backgrounds)
        {
            if (bg?.Name?.Content == null) continue;
            var tpi = GetBackgroundTpi(bg);
            if (tpi == null) continue;
            worker.ExportAsPNG(tpi, Path.Combine(backgroundsOut, SafeName(bg.Name.Content) + ".png"));
        }
    }
    
    foreach (var code in Data.Code)
    {
        if (code?.Name?.Content == null) continue;
        File.WriteAllText(Path.Combine(codeOut, SafeName(code.Name.Content) + ".gml"),
                          Decompile(code) ?? $"// Failed to decompile {code.Name.Content}", Encoding.UTF8);
    }

    WriteAssetOrder(Path.Combine(outputRoot, "AssetOrder.txt"));
    MergeStraySpritesIntoObjects();
    return;
}


PrintLine($"[SmartExport] Loading comparison file from: {comparisonPath}");
UndertaleData comparison;
using (var fs = new FileStream(comparisonPath, FileMode.Open, FileAccess.Read, FileShare.Read))
    comparison = UndertaleIO.Read(fs);


WriteAssetOrder(Path.Combine(outputRoot, "AssetOrder.txt"));
PrintLine("[SmartExport] AssetOrder written");


var comparisonObjects = comparison.GameObjects.ToDictionary(o => o?.Name?.Content ?? "", o => o);
var newObjects = Data.GameObjects
    .Where(o => o?.Name?.Content != null && !comparisonObjects.ContainsKey(o.Name.Content))
    .ToList();

int objectsNew = 0;
if (newObjects.Count > 0 && modNo != "0")  
{
    PrintLine($"[SmartExport] Found {newObjects.Count} new objects");
    
    Directory.CreateDirectory(objDefDir);
    Directory.CreateDirectory(objCodeDir);
    
    var manifest = new List<string> { $"NewObjects Export - Mod {modNo}", $"Total: {newObjects.Count} objects", "" };
    var allNewObjectCode = new Dictionary<string, List<string>>();
    
    foreach (var obj in newObjects)
    {
        var name = obj.Name.Content;
        manifest.Add($"- {name}");
        objectsNew++;
        
        
        string spriteName = (GetProp(obj, "Sprite") as UndertaleSprite)?.Name?.Content;
        string maskName = (GetProp(obj, "MaskSprite") as UndertaleSprite)?.Name?.Content;
        string parentName = (GetProp(obj, "ParentObject") as UndertaleGameObject)?.Name?.Content;
        
        int depth = 0;
        var depthProp = GetProp(obj, "Depth");
        if (depthProp != null)
        {
            if (depthProp is int di) depth = di;
            else if (depthProp is double dd) depth = (int)dd;
        }
        
        bool visible = (GetProp(obj, "Visible") as bool?) ?? false;
        bool solid = (GetProp(obj, "Solid") as bool?) ?? false;
        bool persistent = (GetProp(obj, "Persistent") as bool?) ?? false;
        bool physics = (GetProp(obj, "PhysicsObject") as bool?) ?? false;
        
        
        string prefix = $"gml_Object_{name}_";
		var objCodeEntries = Data.Code
			.Where(c => c?.Name?.Content != null && c.Name.Content.StartsWith(prefix, StringComparison.Ordinal))
			.Select(c => FixEventNameCasing(c.Name.Content))
			.ToList();
        
        allNewObjectCode[name] = objCodeEntries;
        
        
        var def = new StringBuilder();
        def.AppendLine("[Object]");
        def.AppendLine($"Name={name}");
        if (!string.IsNullOrEmpty(spriteName)) def.AppendLine($"SpriteName={spriteName}");
        if (!string.IsNullOrEmpty(maskName)) def.AppendLine($"MaskName={maskName}");
        if (!string.IsNullOrEmpty(parentName)) def.AppendLine($"ParentName={parentName}");
        def.AppendLine($"Depth={depth}");
        def.AppendLine($"Visible={visible}");
        def.AppendLine($"Solid={solid}");
        def.AppendLine($"Persistent={persistent}");
        def.AppendLine($"Physics={physics}");
        
        def.AppendLine("");
        def.AppendLine("[Code]");
        foreach (var codeEntry in objCodeEntries)
        {
            def.AppendLine(codeEntry);
        }
        
        
        string defPath = Path.Combine(objDefDir, SafeName(name) + ".txt");
        File.WriteAllText(defPath, def.ToString(), Encoding.UTF8);
        
        PrintLine($"[Object] {name}: NEW ({objCodeEntries.Count} code entries)");
    }
    
    
    if (newObjects.Count > 0)
    {
        File.WriteAllLines(Path.Combine(newObjRoot, "manifest.txt"), manifest, Encoding.UTF8);
        
        
        File.WriteAllLines(Path.Combine(outputRoot, "NewObjects.txt"), 
            newObjects.Select(o => o.Name.Content), Encoding.UTF8);
    }
}


int spritesNew = 0, spritesChanged = 0;
var cSprites = comparison.Sprites.ToDictionary(s => s?.Name?.Content ?? "", s => s);

using (var worker = new TextureWorker())
{
    foreach (var sprite in Data.Sprites)
    {
        if (sprite?.Name?.Content == null) continue;

        string spriteName = sprite.Name.Content;
        bool isNew = !cSprites.ContainsKey(spriteName);
        bool isChanged = false;

        if (!isNew)
        {
            var c = cSprites[spriteName];
            if (sprite.Textures.Count != c.Textures.Count) isChanged = true;
            else
            {
                for (int i = 0; i < sprite.Textures.Count; i++)
                {
                    var tpiA = GetTpiFromFrame(sprite.Textures[i]);
                    var tpiB = GetTpiFromFrame(c.Textures[i]);
                    if (tpiA == null || tpiB == null) { isChanged = true; break; }
                    if (tpiA.SourceX != tpiB.SourceX ||
                        tpiA.SourceY != tpiB.SourceY ||
                        tpiA.SourceWidth  != tpiB.SourceWidth ||
                        tpiA.SourceHeight != tpiB.SourceHeight ||
                        tpiA.TargetX != tpiB.TargetX ||
                        tpiA.TargetY != tpiB.TargetY ||
                        (tpiA.TexturePage?.Name?.Content ?? "") != (tpiB.TexturePage?.Name?.Content ?? ""))
                    { isChanged = true; break; }
                }
            }
        }

        if (isNew || isChanged)
        {
            string sprDir = Path.Combine(spritesOut, spriteName);
            Directory.CreateDirectory(sprDir);

            for (int i = 0; i < sprite.Textures.Count; i++)
            {
                var tpi = GetTpiFromFrame(sprite.Textures[i]);
                if (tpi != null)
                {
                    string png = Path.Combine(sprDir, $"{SafeName(spriteName)}_{i}.png");
                    worker.ExportAsPNG(tpi, png);
                }
            }
            PrintLine($"[Sprite] {spriteName}: {(isNew ? "NEW" : "CHANGED")}");
            if (isNew) spritesNew++; else spritesChanged++;
        }
    }
}


int bgsNew = 0, bgsChanged = 0;
var cBgs = comparison.Backgrounds.ToDictionary(b => b?.Name?.Content ?? "", b => b);


T GetPropertyValue<T>(object obj, string propName, T defaultValue = default(T))
{
    try
    {
        var prop = obj.GetType().GetProperty(propName, BindingFlags.Public | BindingFlags.Instance);
        if (prop != null)
        {
            var value = prop.GetValue(obj);
            if (value != null && value is T)
                return (T)value;
        }
    }
    catch { }
    return defaultValue;
}

using (var worker = new TextureWorker())
{
    foreach (var bg in Data.Backgrounds)
    {
        if (bg?.Name?.Content == null) continue;
        string name = bg.Name.Content;

        bool isNew = !cBgs.ContainsKey(name);
        bool isChanged = false;

        if (!isNew)
        {
            var c = cBgs[name];
            var a = GetBackgroundTpi(bg);
            var b = GetBackgroundTpi(c);

            if (a == null || b == null) isChanged = (a != b);
            else
            {
                if (a.SourceX != b.SourceX ||
                    a.SourceY != b.SourceY ||
                    a.SourceWidth  != b.SourceWidth ||
                    a.SourceHeight != b.SourceHeight ||
                    a.TargetX != b.TargetX ||
                    a.TargetY != b.TargetY ||
                    (a.TexturePage?.Name?.Content ?? "") != (b.TexturePage?.Name?.Content ?? ""))
                    isChanged = true;
            }
        }

        if (isNew || isChanged)
        {
            var tpi = GetBackgroundTpi(bg);
            if (tpi != null)
            {
                string png = Path.Combine(backgroundsOut, SafeName(name) + ".png");
                worker.ExportAsPNG(tpi, png);
                PrintLine($"[Background] {name}: {(isNew ? "NEW" : "CHANGED")}");
                if (isNew) bgsNew++; else bgsChanged++;
            }
        }
        
        
        
        
        bool tilesetPropsChanged = false;
        if (!isNew)
        {
            var c = cBgs[name];
            
            int bgTileCount = GetPropertyValue<int>(bg, "TileCount", 0);
            int cTileCount = GetPropertyValue<int>(c, "TileCount", 0);
            int bgTileWidth = GetPropertyValue<int>(bg, "TileWidth", 0);
            int cTileWidth = GetPropertyValue<int>(c, "TileWidth", 0);
            int bgTileHeight = GetPropertyValue<int>(bg, "TileHeight", 0);
            int cTileHeight = GetPropertyValue<int>(c, "TileHeight", 0);
            int bgBorderX = GetPropertyValue<int>(bg, "BorderX", 0);
            int cBorderX = GetPropertyValue<int>(c, "BorderX", 0);
            int bgBorderY = GetPropertyValue<int>(bg, "BorderY", 0);
            int cBorderY = GetPropertyValue<int>(c, "BorderY", 0);
            int bgTileColumn = GetPropertyValue<int>(bg, "TileColumn", 0);
            int cTileColumn = GetPropertyValue<int>(c, "TileColumn", 0);
            int bgItemPerTile = GetPropertyValue<int>(bg, "ItemPerTile", 0);
            int cItemPerTile = GetPropertyValue<int>(c, "ItemPerTile", 0);
            bool bgTransparent = GetPropertyValue<bool>(bg, "Transparent", false);
            bool cTransparent = GetPropertyValue<bool>(c, "Transparent", false);
            bool bgSmooth = GetPropertyValue<bool>(bg, "Smooth", false);
            bool cSmooth = GetPropertyValue<bool>(c, "Smooth", false);
            bool bgPreload = GetPropertyValue<bool>(bg, "Preload", false);
            bool cPreload = GetPropertyValue<bool>(c, "Preload", false);
            int bgFrametime = GetPropertyValue<int>(bg, "Frametime", 0);
            int cFrametime = GetPropertyValue<int>(c, "Frametime", 0);
            
            
            if (bgTileCount != cTileCount ||
                bgTileWidth != cTileWidth ||
                bgTileHeight != cTileHeight ||
                bgBorderX != cBorderX ||
                bgBorderY != cBorderY ||
                bgTileColumn != cTileColumn ||
                bgItemPerTile != cItemPerTile ||
                bgTransparent != cTransparent ||
                bgSmooth != cSmooth ||
                bgPreload != cPreload ||
                bgFrametime != cFrametime)
            {
                tilesetPropsChanged = true;
            }
        }
        
        if (isNew || tilesetPropsChanged)
        {
            
            int tileCount = GetPropertyValue<int>(bg, "TileCount", 0);
            int tileWidth = GetPropertyValue<int>(bg, "TileWidth", 0);
            int tileHeight = GetPropertyValue<int>(bg, "TileHeight", 0);
            int borderX = GetPropertyValue<int>(bg, "BorderX", 0);
            int borderY = GetPropertyValue<int>(bg, "BorderY", 0);
            int tileColumn = GetPropertyValue<int>(bg, "TileColumn", 0);
            int itemPerTile = GetPropertyValue<int>(bg, "ItemPerTile", 0);
            bool transparent = GetPropertyValue<bool>(bg, "Transparent", false);
            bool smooth = GetPropertyValue<bool>(bg, "Smooth", false);
            bool preload = GetPropertyValue<bool>(bg, "Preload", false);
            int frametime = GetPropertyValue<int>(bg, "Frametime", 0);
            
            var tilesetJson = new StringBuilder();
            tilesetJson.AppendLine("{");
            tilesetJson.AppendLine($"  \"tile_count\": {tileCount},");
            tilesetJson.AppendLine($"  \"tile_width\": {tileWidth},");
            tilesetJson.AppendLine($"  \"tile_height\": {tileHeight},");
            tilesetJson.AppendLine($"  \"border_x\": {borderX},");
            tilesetJson.AppendLine($"  \"border_y\": {borderY},");
            tilesetJson.AppendLine($"  \"tile_column\": {tileColumn},");
            tilesetJson.AppendLine($"  \"item_per_tile\": {itemPerTile},");
            tilesetJson.AppendLine($"  \"transparent\": {(transparent ? "true" : "false")},");
            tilesetJson.AppendLine($"  \"smooth\": {(smooth ? "true" : "false")},");
            tilesetJson.AppendLine($"  \"preload\": {(preload ? "true" : "false")},");
            tilesetJson.AppendLine($"  \"frametime\": {frametime}");
            tilesetJson.AppendLine("}");
            
            string tilesetJsonPath = Path.Combine(tilesetsOut, SafeName(name) + ".json");
            File.WriteAllText(tilesetJsonPath, tilesetJson.ToString(), Encoding.UTF8);
            if (tilesetPropsChanged) PrintLine($"[Tileset] {name}: Properties changed");
        }
    }
}


string Decompile(UndertaleCode code)
{
    try
    {
        object globalCtx = null;
        Type globalCtxType = null;
        foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
        {
            try
            {
                foreach (var t in asm.GetTypes())
                {
                    if (t.Name == "GlobalDecompileContext" && t.Namespace != null && t.Namespace.EndsWith(".Decompiler"))
                    {
                        globalCtxType = t;
                        try
                        {
                            var ctor = t.GetConstructor(new Type[] { typeof(UndertaleData) });
                            globalCtx = ctor != null ? ctor.Invoke(new object[] { Data }) : Activator.CreateInstance(t);
                            break;
                        } catch { }
                    }
                }
                if (globalCtxType != null) break;
            } catch { }
        }

        Type decCtxType = null;
        foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
        {
            try
            {
                foreach (var t in asm.GetTypes())
                {
                    if (t.Name == "DecompileContext" && t.Namespace != null && t.Namespace.EndsWith(".Decompiler"))
                    { decCtxType = t; break; }
                }
                if (decCtxType != null) break;
            } catch { }
        }

        if (decCtxType != null && globalCtx != null)
        {
            object settings = Data.ToolInfo != null ? Data.ToolInfo.DecompilerSettings : null;

            foreach (var ctor in decCtxType.GetConstructors())
            {
                try
                {
                    var ps = ctor.GetParameters();
                    object ctxInstance = null;
                    if (ps.Length == 3) ctxInstance = ctor.Invoke(new object[] { globalCtx, code, settings });
                    else if (ps.Length == 2) ctxInstance = ctor.Invoke(new object[] { globalCtx, code });
                    else if (ps.Length == 1 && ps[0].ParameterType == typeof(UndertaleCode)) ctxInstance = ctor.Invoke(new object[] { code });
                    else if (ps.Length == 0) ctxInstance = ctor.Invoke(null);

                    if (ctxInstance != null)
                    {
                        var m = decCtxType.GetMethod("DecompileToString", BindingFlags.Public | BindingFlags.Instance);
                        if (m != null && m.GetParameters().Length == 0 && m.ReturnType == typeof(string))
                        {
                            var gml = m.Invoke(ctxInstance, null) as string;
                            if (!string.IsNullOrEmpty(gml)) return gml;
                        }
                    }
                } catch { }
            }
        }
    }
    catch { }

    
    var sb = new StringBuilder();
    sb.AppendLine("/* DECOMPILER UNAVAILABLE - bytecode dump below for reference only */");
    sb.AppendLine($"/* {code?.Name?.Content ?? "unknown"} */");
    foreach (var inst in code.Instructions) sb.AppendLine(inst.ToString());
    return sb.ToString();
}

int codeNew = 0, codeChanged = 0;
var cCode = comparison.Code.ToDictionary(c => c?.Name?.Content ?? "", c => c);

using (var sha = SHA1.Create())
{
    foreach (var code in Data.Code)
    {
        if (code?.Name?.Content == null) continue;
        string codeName = code.Name.Content;

        bool isNew = !cCode.ContainsKey(codeName);
        bool isDifferent = false;

        if (isNew)
        {
            codeNew++; isDifferent = true;
        }
        else
        {
            var cCodeEntry = cCode[codeName];
            if (code.Instructions.Count != cCodeEntry.Instructions.Count) isDifferent = true;
            else
            {
                var modHash = sha.ComputeHash(Encoding.UTF8.GetBytes(string.Join("\n", code.Instructions.Select(i => i.ToString()))));
                var compHash = sha.ComputeHash(Encoding.UTF8.GetBytes(string.Join("\n", cCodeEntry.Instructions.Select(i => i.ToString()))));
                isDifferent = !modHash.SequenceEqual(compHash);
            }
            if (isDifferent) codeChanged++;
        }

        if (isDifferent)
        {
            var path = Path.Combine(codeOut, SafeName(codeName) + ".gml");
            File.WriteAllText(path, Decompile(code), Encoding.UTF8);
            PrintLine($"[Code] {codeName}: {(isNew ? "NEW" : "CHANGED")}");
        }
    }
}


MergeStraySpritesIntoObjects();

int codeCount   = Directory.Exists(codeOut)        ? Directory.EnumerateFiles(codeOut, "*.gml", SearchOption.AllDirectories).Count() : 0;
int spriteCount = Directory.Exists(spritesOut)     ? Directory.EnumerateFiles(spritesOut, "*.png", SearchOption.AllDirectories).Count() : 0;
int bgCount     = Directory.Exists(backgroundsOut) ? Directory.EnumerateFiles(backgroundsOut, "*.png", SearchOption.AllDirectories).Count() : 0;
int objDefCount = Directory.Exists(objDefDir)      ? Directory.EnumerateFiles(objDefDir, "*.txt", SearchOption.AllDirectories).Count() : 0;





PrintLine($"\n[SmartExport] Summary for Mod {modNo}:");
PrintLine($"  Objects      - New: {objectsNew}, Definitions: {objDefCount}");
PrintLine($"  Sprites      - New: {spritesNew}, Changed: {spritesChanged}, Files: {spriteCount}");
PrintLine($"  Backgrounds  - New: {bgsNew},    Changed: {bgsChanged},   Files: {bgCount}");
PrintLine($"  Code         - New: {codeNew},   Changed: {codeChanged},   Files: {codeCount}");
PrintLine($"  Total exports: {objectsNew + spritesNew + spritesChanged + bgsNew + bgsChanged + codeNew + codeChanged}");
PrintLine("[SmartExport] Done.");


UndertaleTexturePageItem GetTpiFromFrame(UndertaleSprite.TextureEntry te)
{
    try
    {
        if (te == null) return null;
        var teType = te.GetType();

        
        var texProp = teType.GetProperty("Texture", BindingFlags.Public | BindingFlags.Instance);
        if (texProp != null)
        {
            var tex = texProp.GetValue(te);

            
            if (tex is UndertaleTexturePageItem tpi0) return tpi0;

            
            if (tex != null)
            {
                var tpiProp = tex.GetType().GetProperty("TexturePageItem", BindingFlags.Public | BindingFlags.Instance);
                if (tpiProp != null)
                {
                    var tpi1 = tpiProp.GetValue(tex) as UndertaleTexturePageItem;
                    if (tpi1 != null) return tpi1;
                }
            }
        }

        
        var direct = teType.GetProperty("TexturePageItem", BindingFlags.Public | BindingFlags.Instance)
                           ?.GetValue(te) as UndertaleTexturePageItem;
        if (direct != null) return direct;

        return null;
    }
    catch { return null; }
}


UndertaleTexturePageItem GetBackgroundTpi(object bgObj)
{
    try
    {
        if (bgObj == null) return null;
        var bgType = bgObj.GetType();

        
        var texProp = bgType.GetProperty("Texture", BindingFlags.Public | BindingFlags.Instance);
        var tex = texProp?.GetValue(bgObj);
        if (tex is UndertaleTexturePageItem tpi0) return tpi0;
        if (tex != null)
        {
            var tpiProp = tex.GetType().GetProperty("TexturePageItem", BindingFlags.Public | BindingFlags.Instance);
            if (tpiProp != null)
            {
                var tpi1 = tpiProp.GetValue(tex) as UndertaleTexturePageItem;
                if (tpi1 != null) return tpi1;
            }
        }

        
        var direct = bgType.GetProperty("TexturePageItem", BindingFlags.Public | BindingFlags.Instance)
                           ?.GetValue(bgObj) as UndertaleTexturePageItem;
        if (direct != null) return direct;

        
        var g = bgType.GetProperty("Graphic", BindingFlags.Public | BindingFlags.Instance)?.GetValue(bgObj);
        if (g != null)
        {
            var tpi2 = g.GetType().GetProperty("TexturePageItem", BindingFlags.Public | BindingFlags.Instance)
                          ?.GetValue(g) as UndertaleTexturePageItem;
            if (tpi2 != null) return tpi2;
        }
    }
    catch { }
    return null;
}

