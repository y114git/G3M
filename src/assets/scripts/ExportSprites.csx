


using System;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Linq;
using System.Reflection;
using System.Threading.Tasks;
using System.Collections.Generic;
using UndertaleModLib;
using UndertaleModLib.Models;
using UndertaleModLib.Util;
using ImageMagick;






void PrintLine(string s) => Console.WriteLine(s);

string SafeName(string name)
{
    var invalid = Path.GetInvalidFileNameChars();
    var sb = new StringBuilder(name.Length);
    foreach (var ch in name) sb.Append(invalid.Contains(ch) ? '_' : ch);
    return sb.ToString();
}

string GetOutputDirectory()
{
    string outputDir = Environment.GetEnvironmentVariable("OUTPUT_DIR");
    if (string.IsNullOrEmpty(outputDir))
        throw new ScriptException("OUTPUT_DIR environment variable is not set.");
    if (!Directory.Exists(outputDir))
        Directory.CreateDirectory(outputDir);
    return outputDir;
}

void ExportSourcePixelsAsPNG(TextureWorker worker, UndertaleTexturePageItem texPageItem, string filePath)
{
    var getEmbeddedMethod = worker.GetType().GetMethod("GetEmbeddedTexture", 
        BindingFlags.Public | BindingFlags.Instance);
    var embeddedImage = getEmbeddedMethod.Invoke(worker, new object[] { texPageItem.TexturePage }) as MagickImage;
    
    if (embeddedImage == null)
        throw new Exception($"Failed to get embedded texture for {filePath}");
    
    IMagickImage<byte> croppedImage;
    lock (embeddedImage)
    {
        croppedImage = embeddedImage.CloneArea(
            texPageItem.SourceX, 
            texPageItem.SourceY, 
            texPageItem.SourceWidth, 
            texPageItem.SourceHeight
        );
    }
    
    croppedImage.Strip();
    
    using (var stream = new FileStream(filePath, FileMode.Create))
    {
        croppedImage.Write(stream, MagickFormat.Png32);
    }
    
    croppedImage.Dispose();
}




EnsureDataLoaded();

if (Data.IsYYC())
{
    PrintLine("[ExportSprites] YYC build detected - sprite export may have limitations.");
}

string spritesOut = GetOutputDirectory();
PrintLine($"[ExportSprites] Exporting to: {spritesOut}");

List<UndertaleSprite> allSprites = Data.Sprites.ToList();
PrintLine($"[ExportSprites] Found {allSprites.Count} sprites to export.");

JsonSerializerOptions jsonWriteOptions = new JsonSerializerOptions 
{ 
    WriteIndented = true,
    Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping
};

SetProgressBar(null, "Exporting Sprites", 0, allSprites.Count);
StartProgressBarUpdater();

using (TextureWorker worker = new TextureWorker())
{
    await Task.Run(() => Parallel.ForEach(allSprites, sprite => ExportSprite(sprite, worker, spritesOut)));
}

void ExportSprite(UndertaleSprite sprite, TextureWorker worker, string outputDir)
{
    if (sprite?.Name?.Content == null)
    {
        IncrementProgressParallel();
        return;
    }

    try
    {
        string spriteName = SafeName(sprite.Name.Content);
        string spriteFolder = Path.Combine(outputDir, spriteName);
        Directory.CreateDirectory(spriteFolder);

        
        for (int i = 0; i < sprite.Textures.Count; i++)
        {
            if (sprite.Textures[i]?.Texture is not null)
            {
                UndertaleTexturePageItem tex = sprite.Textures[i].Texture;
                string pngPath = Path.Combine(spriteFolder, $"{spriteName}_{i}.png");
                ExportSourcePixelsAsPNG(worker, tex, pngPath);
            }
        }

        
        var spriteMeta = new Dictionary<string, object>
        {
            ["name"] = sprite.Name?.Content ?? "",
            ["width"] = sprite.Width,
            ["height"] = sprite.Height,
            ["marginLeft"] = sprite.MarginLeft,
            ["marginRight"] = sprite.MarginRight,
            ["marginTop"] = sprite.MarginTop,
            ["marginBottom"] = sprite.MarginBottom,
            ["originX"] = sprite.OriginX,
            ["originY"] = sprite.OriginY,
            ["transparent"] = sprite.Transparent,
            ["smooth"] = sprite.Smooth,
            ["preload"] = sprite.Preload,
            ["bboxMode"] = sprite.BBoxMode,
            ["sepMasks"] = (uint)sprite.SepMasks,
            ["sepMasksDescription"] = sprite.SepMasks.ToString(),
            ["textureCount"] = sprite.Textures.Count
        };

        
        var textureFrames = new List<Dictionary<string, object>>();
        for (int i = 0; i < sprite.Textures.Count; i++)
        {
            var texEntry = sprite.Textures[i];
            if (texEntry?.Texture != null)
            {
                var tex = texEntry.Texture;
                textureFrames.Add(new Dictionary<string, object>
                {
                    ["frameIndex"] = i,
                    ["sourceX"] = tex.SourceX,
                    ["sourceY"] = tex.SourceY,
                    ["sourceWidth"] = tex.SourceWidth,
                    ["sourceHeight"] = tex.SourceHeight,
                    ["targetX"] = tex.TargetX,
                    ["targetY"] = tex.TargetY,
                    ["targetWidth"] = tex.TargetWidth,
                    ["targetHeight"] = tex.TargetHeight,
                    ["boundingWidth"] = tex.BoundingWidth,
                    ["boundingHeight"] = tex.BoundingHeight
                });
            }
            else
            {
                textureFrames.Add(new Dictionary<string, object>
                {
                    ["frameIndex"] = i,
                    ["isNull"] = true
                });
            }
        }
        spriteMeta["textureFrames"] = textureFrames;

        
        if (Data.IsGameMaker2())
        {
            spriteMeta["isSpecialType"] = sprite.IsSpecialType;
            spriteMeta["sVersion"] = sprite.SVersion;
            spriteMeta["sSpriteType"] = (uint)sprite.SSpriteType;
            spriteMeta["sSpriteTypeDescription"] = sprite.SSpriteType.ToString();
            spriteMeta["gms2PlaybackSpeed"] = sprite.GMS2PlaybackSpeed;
            spriteMeta["gms2PlaybackSpeedType"] = (uint)sprite.GMS2PlaybackSpeedType;
            spriteMeta["gms2PlaybackSpeedTypeDescription"] = sprite.GMS2PlaybackSpeedType.ToString();
        }

        
        if (sprite.CollisionMasks != null && sprite.CollisionMasks.Count > 0)
        {
            var masksData = new List<Dictionary<string, object>>();
            foreach (var mask in sprite.CollisionMasks)
            {
                if (mask?.Data != null && mask.Data.Length > 0)
                {
                    masksData.Add(new Dictionary<string, object>
                    {
                        ["width"] = mask.Width,
                        ["height"] = mask.Height,
                        ["data"] = Convert.ToBase64String(mask.Data)
                    });
                }
            }
            spriteMeta["collisionMasks"] = masksData;
        }

        
        if (sprite.V3NineSlice != null)
        {
            var nineSliceData = new Dictionary<string, object>
            {
                ["left"] = sprite.V3NineSlice.Left,
                ["top"] = sprite.V3NineSlice.Top,
                ["right"] = sprite.V3NineSlice.Right,
                ["bottom"] = sprite.V3NineSlice.Bottom,
                ["enabled"] = sprite.V3NineSlice.Enabled
            };
            
            if (sprite.V3NineSlice.TileModes != null)
            {
                nineSliceData["tileModes"] = sprite.V3NineSlice.TileModes.Select(t => (int)t).ToArray();
            }
            
            spriteMeta["nineSlice"] = nineSliceData;
        }

        
        if (sprite.IsSpineSprite)
        {
            spriteMeta["isSpineSprite"] = true;
            spriteMeta["spineVersion"] = sprite.SpineVersion;
        }

        
        if (sprite.IsYYSWFSprite)
        {
            spriteMeta["isYYSWFSprite"] = true;
            spriteMeta["swfVersion"] = sprite.SWFVersion;
        }

        
        string metaJson = JsonSerializer.Serialize(spriteMeta, jsonWriteOptions);
        string metaFile = Path.Combine(spriteFolder, $"{spriteName}.json");
        File.WriteAllText(metaFile, metaJson, Encoding.UTF8);
    }
    catch (Exception ex)
    {
        PrintLine($"[ExportSprites] Failed to export sprite {sprite.Name?.Content}: {ex.Message}");
    }

    IncrementProgressParallel();
}

await StopProgressBarUpdater();
HideProgressBar();

PrintLine($"[ExportSprites] Export complete. {allSprites.Count} sprites exported to {spritesOut}");
