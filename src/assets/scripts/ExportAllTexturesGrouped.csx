#load "SharedPaths.csx"

using System;
using System.IO;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Reflection;
using UndertaleModLib.Util;
using UndertaleModCli;

EnsureDataLoaded();

string deltahubRoot = null;
try
{
    deltahubRoot = FindDeltahubRoot();
}
catch
{
    if (!string.IsNullOrEmpty(FilePath))
    {
        var dataWinDir = new DirectoryInfo(Path.GetDirectoryName(FilePath));
        var probe = dataWinDir;
        while (probe != null)
        {
            if (Directory.Exists(Path.Combine(probe.FullName, "output"))) { deltahubRoot = probe.FullName; break; }
            probe = probe.Parent;
        }
    }
    
    if (deltahubRoot == null)
    {
        var entryAssembly = Assembly.GetEntryAssembly();
        if (entryAssembly != null && !string.IsNullOrEmpty(entryAssembly.Location))
        {
            var firstParent = Directory.GetParent(entryAssembly.Location);
            if (firstParent != null)
            {
                var assemblyRoot = Directory.GetParent(firstParent.FullName);
                if (assemblyRoot != null && Directory.Exists(Path.Combine(assemblyRoot.FullName, "output")))
                {
                    deltahubRoot = assemblyRoot.FullName;
                }
            }
        }
    }
    
    if (deltahubRoot == null)
        throw new ScriptException("DELTAHUB root not found (no /output ancestor).");
}

string chapterNo = File.ReadAllText(Path.Combine(deltahubRoot, "output", "Cache", "running", "chapterNumber.txt"));
string modNo = File.ReadAllText(Path.Combine(deltahubRoot, "output", "Cache", "running", "modNumbersCache.txt"));
string texFolder = Path.Combine(deltahubRoot, "output", "xDeltaCombiner", chapterNo, modNo, "Objects");
if (string.IsNullOrEmpty(texFolder) || !Directory.Exists(texFolder))
{
    throw new ScriptException("Texture folder not found: " + texFolder);
}


string sprFolder = Path.Combine(@texFolder, "Sprites");
Directory.CreateDirectory(sprFolder);
string fntFolder = Path.Combine(@texFolder, "Fonts");
Directory.CreateDirectory(fntFolder);
string bgrFolder = Path.Combine(@texFolder, "Backgrounds");
Directory.CreateDirectory(bgrFolder);


UndertaleData vanillaData = LoadVanillaData();
Dictionary<string, UndertaleSprite> vanillaSprites = new Dictionary<string, UndertaleSprite>();
Dictionary<string, UndertaleBackground> vanillaBackgrounds = new Dictionary<string, UndertaleBackground>();
Dictionary<string, UndertaleFont> vanillaFonts = new Dictionary<string, UndertaleFont>();

if (vanillaData != null)
{
    foreach(var s in vanillaData.Sprites) if (s?.Name?.Content != null) vanillaSprites[s.Name.Content] = s;
    foreach(var b in vanillaData.Backgrounds) if (b?.Name?.Content != null) vanillaBackgrounds[b.Name.Content] = b;
    foreach(var f in vanillaData.Fonts) if (f?.Name?.Content != null) vanillaFonts[f.Name.Content] = f;
}

bool IsTextureItemChanged(UndertaleTexturePageItem current, UndertaleTexturePageItem vanilla)
{
    if (current == null && vanilla == null) return false;
    if (current == null || vanilla == null) return true;
    
    
    if (current.SourceX != vanilla.SourceX || current.SourceY != vanilla.SourceY ||
        current.SourceWidth != vanilla.SourceWidth || current.SourceHeight != vanilla.SourceHeight)
        return true;
        
    
    
    
    
    
    if (current.TexturePage?.Name?.Content != vanilla.TexturePage?.Name?.Content)
        return true;

    return false;
}


List<UndertaleSprite> changedSprites = new List<UndertaleSprite>();
foreach(var spr in Data.Sprites)
{
    string name = spr.Name.Content;
    if (vanillaData == null || !vanillaSprites.ContainsKey(name)) { changedSprites.Add(spr); LogDiff("Sprite", name, "New"); continue; }
    
    var vSpr = vanillaSprites[name];
    if (spr.Width != vSpr.Width || spr.Height != vSpr.Height || 
        spr.MarginLeft != vSpr.MarginLeft || spr.MarginRight != vSpr.MarginRight ||
        spr.MarginTop != vSpr.MarginTop || spr.MarginBottom != vSpr.MarginBottom ||
        spr.OriginX != vSpr.OriginX || spr.OriginY != vSpr.OriginY ||
        spr.Textures.Count != vSpr.Textures.Count)
    {
        changedSprites.Add(spr); LogDiff("Sprite", name, "Props mismatch"); continue;
    }

    bool texChanged = false;
    for(int i=0; i<spr.Textures.Count; i++)
    {
        if (IsTextureItemChanged(spr.Textures[i].Texture, vSpr.Textures[i].Texture)) { texChanged = true; break; }
    }
    if (texChanged) { changedSprites.Add(spr); LogDiff("Sprite", name, "Texture changed"); }
    else LogSkip("Sprite", name);
}


List<UndertaleBackground> changedBackgrounds = new List<UndertaleBackground>();
foreach(var bg in Data.Backgrounds)
{
    string name = bg.Name.Content;
    if (vanillaData == null || !vanillaBackgrounds.ContainsKey(name)) { changedBackgrounds.Add(bg); LogDiff("BG", name, "New"); continue; }
    
    var vBg = vanillaBackgrounds[name];
    if (bg.Transparent != vBg.Transparent || bg.Preload != vBg.Preload ||
        IsTextureItemChanged(bg.Texture, vBg.Texture))
    {
        changedBackgrounds.Add(bg); LogDiff("BG", name, "Changed");
    }
    else LogSkip("BG", name);
}





SetProgressBar(null, "Exporting Changed Textures", 0, changedSprites.Count + changedBackgrounds.Count);
StartProgressBarUpdater();

TextureWorker worker = null;
using (worker = new())
{
    await DumpSprites();
    
    await DumpBackgrounds();
}

await StopProgressBarUpdater();
HideProgressBar();

async Task DumpSprites()
{
    await Task.Run(() => Parallel.ForEach(changedSprites, DumpSprite));
}

async Task DumpBackgrounds()
{
    await Task.Run(() => Parallel.ForEach(changedBackgrounds, DumpBackground));
}

void DumpSprite(UndertaleSprite sprite)
{
    if (sprite is null)
    {
        return;
    }

    for (int i = 0; i < sprite.Textures.Count; i++)
    {
        if (sprite.Textures[i]?.Texture is not null)
        {
            UndertaleTexturePageItem tex = sprite.Textures[i].Texture;
            string sprFolder2 = Path.Combine(sprFolder, sprite.Name.Content);
            Directory.CreateDirectory(sprFolder2);
            worker.ExportAsPNG(tex, Path.Combine(sprFolder2, $"{sprite.Name.Content}_{i}.png"));
        }
    }

    AddProgressParallel(sprite.Textures.Count);
}

void DumpFont(UndertaleFont font)
{
    if (font?.Texture is null)
    {
        return;
    }

    UndertaleTexturePageItem tex = font.Texture;
    string fntFolder2 = Path.Combine(fntFolder, font.Name.Content);
    Directory.CreateDirectory(fntFolder2);
    worker.ExportAsPNG(tex, Path.Combine(fntFolder2, $"{font.Name.Content}_0.png"));
    IncrementProgressParallel();
}

void DumpBackground(UndertaleBackground background)
{
    if (background?.Texture is null)
    {
        return;
    }

    UndertaleTexturePageItem tex = background.Texture;
    string bgrFolder2 = Path.Combine(bgrFolder, background.Name.Content);
    Directory.CreateDirectory(bgrFolder2);
    worker.ExportAsPNG(tex, Path.Combine(bgrFolder2, $"{background.Name.Content}_0.png"));
    IncrementProgressParallel();
}