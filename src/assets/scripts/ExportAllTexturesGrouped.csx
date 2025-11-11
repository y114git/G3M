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

// Try to find DELTAHUB root (same approach as ExportModifiedOnly.csx)
string gm3pRoot = null;
{
    // Method 1: Check current working directory
    var probe = new DirectoryInfo(Directory.GetCurrentDirectory());
    while (probe != null)
    {
        if (Directory.Exists(Path.Combine(probe.FullName, "output"))) { gm3pRoot = probe.FullName; break; }
        probe = probe.Parent;
    }
    // Method 2: Try data.win location (FilePath)
    if (gm3pRoot == null && !string.IsNullOrEmpty(FilePath))
    {
        var dataWinDir = new DirectoryInfo(Path.GetDirectoryName(FilePath));
        probe = dataWinDir;
        while (probe != null)
        {
            if (Directory.Exists(Path.Combine(probe.FullName, "output"))) { gm3pRoot = probe.FullName; break; }
            probe = probe.Parent;
        }
    }
    // Method 3: Fallback to Assembly location (original behavior)
    if (gm3pRoot == null)
    {
        var assemblyRoot = Directory.GetParent(Directory.GetParent(Assembly.GetEntryAssembly().Location));
        if (assemblyRoot != null && Directory.Exists(Path.Combine(assemblyRoot.FullName, "output")))
        {
            gm3pRoot = assemblyRoot.FullName;
        }
    }
}

if (gm3pRoot == null)
    throw new ScriptException("DELTAHUB root not found (no /output ancestor).");

string chapterNo = File.ReadAllText(Path.Combine(gm3pRoot, "output", "Cache", "running", "chapterNumber.txt"));
string modNo = File.ReadAllText(Path.Combine(gm3pRoot, "output", "Cache", "running", "modNumbersCache.txt"));
string texFolder = Path.Combine(gm3pRoot, "output", "xDeltaCombiner", chapterNo, modNo, "Objects");
if (string.IsNullOrEmpty(texFolder) || !Directory.Exists(texFolder))
{
    throw new ScriptException("Texture folder not found: " + texFolder);
}

        // Create subdirectories.
        string sprFolder = Path.Combine(@texFolder, "Sprites");
        Directory.CreateDirectory(sprFolder);
        string fntFolder = Path.Combine(@texFolder, "Fonts");
        Directory.CreateDirectory(fntFolder);
        string bgrFolder = Path.Combine(@texFolder, "Backgrounds");
        Directory.CreateDirectory(bgrFolder);

        SetProgressBar(null, "Textures", 0, Data.TexturePageItems.Count);
        StartProgressBarUpdater();

        TextureWorker worker = null;
        using (worker = new())
        {
            await DumpSprites();
            await DumpFonts();
            await DumpBackgrounds();
        }

        await StopProgressBarUpdater();
        HideProgressBar();

        async Task DumpSprites()
        {
            await Task.Run(() => Parallel.ForEach(Data.Sprites, DumpSprite));
        }

        async Task DumpBackgrounds()
        {
            await Task.Run(() => Parallel.ForEach(Data.Backgrounds, DumpBackground));
        }

        async Task DumpFonts()
        {
            await Task.Run(() => Parallel.ForEach(Data.Fonts, DumpFont));
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
//    }
//}