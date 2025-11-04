// ExportModifiedOnly.csx — GM3P Script.

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
bool DEBUG = Environment.GetEnvironmentVariable("GM3P_DEBUG") == "1";
void DebugLog(string s) { if (DEBUG) PrintLine($"[DEBUG] {s}"); }

string FixEventNameCasing(string codeName)
{
    // GameMaker event name mappings (case-sensitive)
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
            // Replace with case-insensitive search but case-sensitive replacement
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
    PrintLine("[ExportModifiedOnly] YYC build detected – code export not available.");
    return;
}

// ── locate GM3P root (ancestor holding /output)
string gm3pRoot = null;
{
    var probe = new DirectoryInfo(Directory.GetCurrentDirectory());
    while (probe != null)
    {
        if (Directory.Exists(Path.Combine(probe.FullName, "output"))) { gm3pRoot = probe.FullName; break; }
        probe = probe.Parent;
    }
        // If UTMT was called but not as a child of GM3P 
        if (gm3pRoot == null)
        {
            // Resolve GM3P root → output/xDeltaCombiner/<chapter>/1/Objects (no prompts)
            string TryRoot(string root)
            {
                if (string.IsNullOrWhiteSpace(root)) return null;
                string folder    = Path.Combine(root);
                return Directory.Exists(folder) ? folder : null;
            }

            var got = TryRoot(@Convert.ToString(Directory.GetParent(Convert.ToString(Directory.GetParent(Convert.ToString(Assembly.GetEntryAssembly().Location))))));
            if (got!=null){ gm3pRoot = got;}

        }
    
    if (gm3pRoot == null) throw new ScriptException("GM3P root not found (no /output ancestor).");
}

// ── run context provided by GM3P
string chapterNo = ReadAllTextSafe(Path.Combine(gm3pRoot, "output", "Cache", "running", "chapterNumber.txt"));
string modNo     = ReadAllTextSafe(Path.Combine(gm3pRoot, "output", "Cache", "running", "modNumbersCache.txt"));
if (string.IsNullOrWhiteSpace(chapterNo) || string.IsNullOrWhiteSpace(modNo))
    throw new ScriptException("chapterNumber/modNumbersCache missing in /output/Cache/running/." + Convert.ToString(Path.Combine(gm3pRoot, "output", "Cache", "running", "modNumbersCache.txt")));

// ── output layout (everything under Objects/)
string modRoot         = Path.Combine(gm3pRoot, "output", "xDeltaCombiner", chapterNo, modNo);
string outputRoot      = Path.Combine(modRoot, "Objects");
string codeOut         = Path.Combine(outputRoot, "CodeEntries");
string spritesOut      = Path.Combine(outputRoot, "Sprites");
string backgroundsOut  = Path.Combine(outputRoot, "Backgrounds");
string newObjRoot      = Path.Combine(outputRoot, "NewObjects");
string objDefDir       = Path.Combine(newObjRoot, "ObjectDefinitions");
string objCodeDir      = Path.Combine(newObjRoot, "CodeEntries");

Directory.CreateDirectory(outputRoot);
Directory.CreateDirectory(codeOut);
Directory.CreateDirectory(spritesOut);
Directory.CreateDirectory(backgroundsOut);

// ── if someone created a stray root-level /Sprites, move it inside Objects/Sprites
void MergeStraySpritesIntoObjects()
{
    var stray = Path.Combine(modRoot, "Sprites");
    if (!Directory.Exists(stray)) return;
    PrintLine("[ExportModifiedOnly] WARNING: Found stray Sprites at mod root; moving into Objects/Sprites.");

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

// ── vanilla path for comparison
string vanillaPath = Path.Combine(gm3pRoot, "output", "xDeltaCombiner", chapterNo, "0", "data.win");

// ── AssetOrder writer (into Objects/)
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

// ── FULL FALLBACK if vanilla not present
if (!File.Exists(vanillaPath))
{
    PrintLine($"[ExportModifiedOnly] ERROR: Vanilla not found at {vanillaPath}");
    PrintLine("[ExportModifiedOnly] Falling back to full export...");

    using (var worker = new TextureWorker())
    {
        // sprites
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
        // backgrounds
        foreach (var bg in Data.Backgrounds)
        {
            if (bg?.Name?.Content == null) continue;
            var tpi = GetBackgroundTpi(bg);
            if (tpi == null) continue;
            worker.ExportAsPNG(tpi, Path.Combine(backgroundsOut, SafeName(bg.Name.Content) + ".png"));
        }
    }
    // code
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

// ── load vanilla for diff
PrintLine($"[ExportModifiedOnly] Loading vanilla from: {vanillaPath}");
UndertaleData vanilla;
using (var fs = new FileStream(vanillaPath, FileMode.Open, FileAccess.Read, FileShare.Read))
    vanilla = UndertaleIO.Read(fs);

// always write AssetOrder
WriteAssetOrder(Path.Combine(outputRoot, "AssetOrder.txt"));
PrintLine("[ExportModifiedOnly] AssetOrder written");

// ── NEW OBJECTS (GameObjects that don't exist in vanilla)
var vanillaObjects = vanilla.GameObjects.ToDictionary(o => o?.Name?.Content ?? "", o => o);
var newObjects = Data.GameObjects
    .Where(o => o?.Name?.Content != null && !vanillaObjects.ContainsKey(o.Name.Content))
    .ToList();

int objectsNew = 0;
if (newObjects.Count > 0 && modNo != "0")  // Skip for vanilla
{
    PrintLine($"[ExportModifiedOnly] Found {newObjects.Count} new objects");
    
    Directory.CreateDirectory(objDefDir);
    Directory.CreateDirectory(objCodeDir);
    
    var manifest = new List<string> { $"NewObjects Export - Mod {modNo}", $"Total: {newObjects.Count} objects", "" };
    var allNewObjectCode = new Dictionary<string, List<string>>();
    
    foreach (var obj in newObjects)
    {
        var name = obj.Name.Content;
        manifest.Add($"- {name}");
        objectsNew++;
        
        // Get object properties
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
        
        // Find all code entries for this object
        string prefix = $"gml_Object_{name}_";
		var objCodeEntries = Data.Code
			.Where(c => c?.Name?.Content != null && c.Name.Content.StartsWith(prefix, StringComparison.Ordinal))
			.Select(c => FixEventNameCasing(c.Name.Content))
			.ToList();
        
        allNewObjectCode[name] = objCodeEntries;
        
        // Write object definition
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
        
        // Save definition
        string defPath = Path.Combine(objDefDir, SafeName(name) + ".txt");
        File.WriteAllText(defPath, def.ToString(), Encoding.UTF8);
        
        PrintLine($"[Object] {name}: NEW ({objCodeEntries.Count} code entries)");
    }
    
    // Write manifest
    if (newObjects.Count > 0)
    {
        File.WriteAllLines(Path.Combine(newObjRoot, "manifest.txt"), manifest, Encoding.UTF8);
        
        // Also write a simple list for compatibility
        File.WriteAllLines(Path.Combine(outputRoot, "NewObjects.txt"), 
            newObjects.Select(o => o.Name.Content), Encoding.UTF8);
    }
}

// ── SPRITES diff
int spritesNew = 0, spritesChanged = 0;
var vSprites = vanilla.Sprites.ToDictionary(s => s?.Name?.Content ?? "", s => s);

using (var worker = new TextureWorker())
{
    foreach (var sprite in Data.Sprites)
    {
        if (sprite?.Name?.Content == null) continue;

        string spriteName = sprite.Name.Content;
        bool isNew = !vSprites.ContainsKey(spriteName);
        bool isChanged = false;

        if (!isNew)
        {
            var v = vSprites[spriteName];
            if (sprite.Textures.Count != v.Textures.Count) isChanged = true;
            else
            {
                for (int i = 0; i < sprite.Textures.Count; i++)
                {
                    var tpiA = GetTpiFromFrame(sprite.Textures[i]);
                    var tpiB = GetTpiFromFrame(v.Textures[i]);
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

// ── BACKGROUNDS diff
int bgsNew = 0, bgsChanged = 0;
var vBgs = vanilla.Backgrounds.ToDictionary(b => b?.Name?.Content ?? "", b => b);

using (var worker = new TextureWorker())
{
    foreach (var bg in Data.Backgrounds)
    {
        if (bg?.Name?.Content == null) continue;
        string name = bg.Name.Content;

        bool isNew = !vBgs.ContainsKey(name);
        bool isChanged = false;

        if (!isNew)
        {
            var v = vBgs[name];
            var a = GetBackgroundTpi(bg);
            var b = GetBackgroundTpi(v);

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
    }
}

// ── CODE diff
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

    // fallback: bytecode
    var sb = new StringBuilder();
    sb.AppendLine("/* DECOMPILER UNAVAILABLE - bytecode dump below for reference only */");
    sb.AppendLine($"/* {code?.Name?.Content ?? "unknown"} */");
    foreach (var inst in code.Instructions) sb.AppendLine(inst.ToString());
    return sb.ToString();
}

int codeNew = 0, codeChanged = 0;
var vCode = vanilla.Code.ToDictionary(c => c?.Name?.Content ?? "", c => c);

using (var sha = SHA1.Create())
{
    foreach (var code in Data.Code)
    {
        if (code?.Name?.Content == null) continue;
        string codeName = code.Name.Content;

        bool isNew = !vCode.ContainsKey(codeName);
        bool isDifferent = false;

        if (isNew)
        {
            codeNew++; isDifferent = true;
        }
        else
        {
            var vCodeEntry = vCode[codeName];
            if (code.Instructions.Count != vCodeEntry.Instructions.Count) isDifferent = true;
            else
            {
                var modHash = sha.ComputeHash(Encoding.UTF8.GetBytes(string.Join("\n", code.Instructions.Select(i => i.ToString()))));
                var vanHash = sha.ComputeHash(Encoding.UTF8.GetBytes(string.Join("\n", vCodeEntry.Instructions.Select(i => i.ToString()))));
                isDifferent = !modHash.SequenceEqual(vanHash);
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

// ── final sanity + summary
MergeStraySpritesIntoObjects();

int codeCount   = Directory.Exists(codeOut)        ? Directory.EnumerateFiles(codeOut, "*.gml", SearchOption.AllDirectories).Count() : 0;
int spriteCount = Directory.Exists(spritesOut)     ? Directory.EnumerateFiles(spritesOut, "*.png", SearchOption.AllDirectories).Count() : 0;
int bgCount     = Directory.Exists(backgroundsOut) ? Directory.EnumerateFiles(backgroundsOut, "*.png", SearchOption.AllDirectories).Count() : 0;
int objDefCount = Directory.Exists(objDefDir)      ? Directory.EnumerateFiles(objDefDir, "*.txt", SearchOption.AllDirectories).Count() : 0;

PrintLine($"\n[ExportModifiedOnly] Summary for Mod {modNo}:");
PrintLine($"  Objects      - New: {objectsNew}, Definitions: {objDefCount}");
PrintLine($"  Sprites      - New: {spritesNew}, Changed: {spritesChanged}, Files: {spriteCount}");
PrintLine($"  Backgrounds  - New: {bgsNew},    Changed: {bgsChanged},   Files: {bgCount}");
PrintLine($"  Code         - New: {codeNew},   Changed: {codeChanged},   Files: {codeCount}");
PrintLine($"  Total exports: {objectsNew + spritesNew + spritesChanged + bgsNew + bgsChanged + codeNew + codeChanged}");
PrintLine("[ExportModifiedOnly] Done.");

// ── helpers (written to avoid compile-time dependency on fork-specific members)
UndertaleTexturePageItem GetTpiFromFrame(UndertaleSprite.TextureEntry te)
{
    try
    {
        if (te == null) return null;
        var teType = te.GetType();

        // 1) Texture property present?
        var texProp = teType.GetProperty("Texture", BindingFlags.Public | BindingFlags.Instance);
        if (texProp != null)
        {
            var tex = texProp.GetValue(te);

            // 1a) In some forks this is already the TPI
            if (tex is UndertaleTexturePageItem tpi0) return tpi0;

            // 1b) In others, it's an UndertaleTexture which has .TexturePageItem
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

        // 2) Some forks expose .TexturePageItem directly on the TextureEntry
        var direct = teType.GetProperty("TexturePageItem", BindingFlags.Public | BindingFlags.Instance)
                           ?.GetValue(te) as UndertaleTexturePageItem;
        if (direct != null) return direct;

        return null;
    }
    catch { return null; }
}

// Resolve a background's TexturePageItem using reflection so it works across UTMT forks.
UndertaleTexturePageItem GetBackgroundTpi(object bgObj)
{
    try
    {
        if (bgObj == null) return null;
        var bgType = bgObj.GetType();

        // 1) bg.Texture?.TexturePageItem *or* bg.Texture is already TPI
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

        // 2) bg.TexturePageItem (direct)
        var direct = bgType.GetProperty("TexturePageItem", BindingFlags.Public | BindingFlags.Instance)
                           ?.GetValue(bgObj) as UndertaleTexturePageItem;
        if (direct != null) return direct;

        // 3) bg.Graphic?.TexturePageItem
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