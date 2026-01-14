


using System;
using System.IO;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using UndertaleModLib.Util;
using UndertaleModLib.Models;
using ImageMagick;

EnsureDataLoaded();

static List<MagickImage> imagesToCleanup = new();
bool importAsSprite = true;





Regex sprFrameRegex = new(@"^(.+?)(?:_(\d+))$", RegexOptions.Compiled);
string importFolder = CheckValidity();

bool noMasksForBasicRectangles = Data.IsVersionAtLeast(2022, 9);


Dictionary<string, JsonElement?> spriteMetadataCache = new();


JsonElement? TryLoadSpriteMetadata(string spritesFolder, string spriteName)
{
    if (spriteMetadataCache.TryGetValue(spriteName, out JsonElement? cached))
        return cached;

    
    string spriteFolder = Path.Combine(spritesFolder, spriteName);
    string metaFile = Path.Combine(spriteFolder, "sprite_meta.json");
    
    if (!File.Exists(metaFile))
    {
        spriteMetadataCache[spriteName] = null;
        return null;
    }

    try
    {
        string jsonContent = File.ReadAllText(metaFile, Encoding.UTF8);
        JsonDocument jsonDoc = JsonDocument.Parse(jsonContent);
        spriteMetadataCache[spriteName] = jsonDoc.RootElement.Clone();
        return spriteMetadataCache[spriteName];
    }
    catch
    {
        spriteMetadataCache[spriteName] = null;
        return null;
    }
}


void ApplySpriteMetadata(UndertaleSprite sprite, JsonElement meta)
{
    
    if (meta.TryGetProperty("originX", out JsonElement originX))
        sprite.OriginX = originX.GetInt32();
    if (meta.TryGetProperty("originY", out JsonElement originY))
        sprite.OriginY = originY.GetInt32();

    
    if (meta.TryGetProperty("marginLeft", out JsonElement marginLeft))
        sprite.MarginLeft = marginLeft.GetInt32();
    if (meta.TryGetProperty("marginRight", out JsonElement marginRight))
        sprite.MarginRight = marginRight.GetInt32();
    if (meta.TryGetProperty("marginTop", out JsonElement marginTop))
        sprite.MarginTop = marginTop.GetInt32();
    if (meta.TryGetProperty("marginBottom", out JsonElement marginBottom))
        sprite.MarginBottom = marginBottom.GetInt32();

    
    if (meta.TryGetProperty("transparent", out JsonElement transparent))
        sprite.Transparent = transparent.GetBoolean();
    if (meta.TryGetProperty("smooth", out JsonElement smooth))
        sprite.Smooth = smooth.GetBoolean();
    if (meta.TryGetProperty("preload", out JsonElement preload))
        sprite.Preload = preload.GetBoolean();

    
    if (meta.TryGetProperty("bboxMode", out JsonElement bboxMode))
        sprite.BBoxMode = (uint)bboxMode.GetInt64();
    if (meta.TryGetProperty("sepMasks", out JsonElement sepMasks))
        sprite.SepMasks = (UndertaleSprite.SepMaskType)sepMasks.GetInt32();

    
    if (Data.IsGameMaker2())
    {
        if (meta.TryGetProperty("gms2PlaybackSpeed", out JsonElement playbackSpeed))
            sprite.GMS2PlaybackSpeed = (float)playbackSpeed.GetDouble();
        if (meta.TryGetProperty("gms2PlaybackSpeedType", out JsonElement playbackSpeedType))
            sprite.GMS2PlaybackSpeedType = (AnimSpeedType)playbackSpeedType.GetInt32();
    }

    
    if (meta.TryGetProperty("collisionMasks", out JsonElement masksElm) && masksElm.ValueKind == JsonValueKind.Array)
    {
        sprite.CollisionMasks.Clear();
        foreach (JsonElement maskElm in masksElm.EnumerateArray())
        {
            if (maskElm.TryGetProperty("data", out JsonElement dataElm) &&
                maskElm.TryGetProperty("width", out JsonElement widthElm) &&
                maskElm.TryGetProperty("height", out JsonElement heightElm))
            {
                byte[] maskData = Convert.FromBase64String(dataElm.GetString());
                int maskWidth = widthElm.GetInt32();
                int maskHeight = heightElm.GetInt32();
                var maskEntry = new UndertaleSprite.MaskEntry(maskData, maskWidth, maskHeight);
                sprite.CollisionMasks.Add(maskEntry);
            }
        }
    }

    
    if (meta.TryGetProperty("nineSlice", out JsonElement nineSlice) && Data.IsVersionAtLeast(2, 3, 2))
    {
        if (sprite.V3NineSlice == null)
            sprite.V3NineSlice = new UndertaleSprite.NineSlice();

        if (nineSlice.TryGetProperty("left", out JsonElement nsLeft))
            sprite.V3NineSlice.Left = nsLeft.GetInt32();
        if (nineSlice.TryGetProperty("top", out JsonElement nsTop))
            sprite.V3NineSlice.Top = nsTop.GetInt32();
        if (nineSlice.TryGetProperty("right", out JsonElement nsRight))
            sprite.V3NineSlice.Right = nsRight.GetInt32();
        if (nineSlice.TryGetProperty("bottom", out JsonElement nsBottom))
            sprite.V3NineSlice.Bottom = nsBottom.GetInt32();
        if (nineSlice.TryGetProperty("enabled", out JsonElement nsEnabled))
            sprite.V3NineSlice.Enabled = nsEnabled.GetBoolean();
        
        
        if (nineSlice.TryGetProperty("tileModes", out JsonElement tileModes) && tileModes.ValueKind == JsonValueKind.Array)
        {
            var modesArray = tileModes.EnumerateArray().ToArray();
            for (int i = 0; i < Math.Min(5, modesArray.Length); i++)
            {
                sprite.V3NineSlice.TileModes[i] = (UndertaleSprite.NineSlice.TileMode)modesArray[i].GetInt32();
            }
        }
    }
}


Dictionary<string, List<Dictionary<string, object>>> textureFrameCache = new();


List<Dictionary<string, object>> TryGetTextureFrameData(string spritesFolder, string spriteName)
{
    if (textureFrameCache.TryGetValue(spriteName, out var cached))
        return cached;

    JsonElement? meta = TryLoadSpriteMetadata(spritesFolder, spriteName);
    if (meta.HasValue && meta.Value.TryGetProperty("textureFrames", out JsonElement framesElm) && framesElm.ValueKind == JsonValueKind.Array)
    {
        var frames = new List<Dictionary<string, object>>();
        foreach (var frameElm in framesElm.EnumerateArray())
        {
            var frame = new Dictionary<string, object>();
            if (frameElm.TryGetProperty("frameIndex", out JsonElement idxElm))
                frame["frameIndex"] = idxElm.GetInt32();
            if (frameElm.TryGetProperty("isNull", out JsonElement nullElm))
                frame["isNull"] = nullElm.GetBoolean();
            if (frameElm.TryGetProperty("targetX", out JsonElement txElm))
                frame["targetX"] = (ushort)txElm.GetInt32();
            if (frameElm.TryGetProperty("targetY", out JsonElement tyElm))
                frame["targetY"] = (ushort)tyElm.GetInt32();
            if (frameElm.TryGetProperty("targetWidth", out JsonElement twElm))
                frame["targetWidth"] = (ushort)twElm.GetInt32();
            if (frameElm.TryGetProperty("targetHeight", out JsonElement thElm))
                frame["targetHeight"] = (ushort)thElm.GetInt32();
            if (frameElm.TryGetProperty("boundingWidth", out JsonElement bwElm))
                frame["boundingWidth"] = (ushort)bwElm.GetInt32();
            if (frameElm.TryGetProperty("boundingHeight", out JsonElement bhElm))
                frame["boundingHeight"] = (ushort)bhElm.GetInt32();
            frames.Add(frame);
        }
        textureFrameCache[spriteName] = frames;
        return frames;
    }

    textureFrameCache[spriteName] = null;
    return null;
}





void ApplyTextureFrameProperties(UndertaleTexturePageItem tpi, string spriteName, int frameIndex, List<Dictionary<string, object>> frameData)
{
    if (frameData == null || frameIndex >= frameData.Count)
        return;

    var frame = frameData[frameIndex];
    if (frame.ContainsKey("isNull") && (bool)frame["isNull"])
        return;
    
    
    if (frame.ContainsKey("targetX"))
        tpi.TargetX = (ushort)frame["targetX"];
    if (frame.ContainsKey("targetY"))
        tpi.TargetY = (ushort)frame["targetY"];
    
    
    if (frame.ContainsKey("targetWidth"))
        tpi.TargetWidth = (ushort)frame["targetWidth"];
    if (frame.ContainsKey("targetHeight"))
        tpi.TargetHeight = (ushort)frame["targetHeight"];

    
    
    
    
    
    
    
    
}

try
{
    
    
    
    string dataWinDir = Path.GetDirectoryName(FilePath);
    string packDir = Path.Combine(dataWinDir, "Packager");
    
    
    
    if (!dataWinDir.Contains("DeltahubMergeWorkspace"))
    {
        
        
        throw new ScriptException($"Packager cannot be created in game directory. Expected temporary folder (DeltahubMergeWorkspace), but got: {dataWinDir}");
    }
    Directory.CreateDirectory(packDir);


    string spritesPath = Path.Combine(importFolder, "Sprites");
    if (!Directory.Exists(spritesPath))
    {
        ScriptMessage("No Sprites folder found in Objects - no sprites to import");
        return;
    }


    var pngFiles = Directory.GetFiles(spritesPath, "*.png", SearchOption.AllDirectories);
    if (pngFiles.Length == 0)
    {
        ScriptMessage("No PNG files found in Sprites folder - nothing to import");
        return;
    }

    ScriptMessage($"Found {pngFiles.Length} PNG files to pack in {spritesPath}");

    string sourcePath = spritesPath;
    string searchPattern = "*.png";
    string outName = Path.Combine(packDir, "atlas.txt");
    int textureSize = 2048;
    int PaddingValue = 2;
    bool debug = false;

    Packer packer = new Packer();
    packer.Process(sourcePath, searchPattern, textureSize, PaddingValue, debug);
    packer.SaveAtlasses(outName);

    int lastTextPage = Data.EmbeddedTextures.Count - 1;
    int lastTextPageItem = Data.TexturePageItems.Count - 1;

    bool bboxMasks = Data.IsVersionAtLeast(2024, 6);
    Dictionary<UndertaleSprite, Node> maskNodes = new();


    string prefix = outName.Replace(Path.GetExtension(outName), "");
    int atlasCount = 0;
    foreach (Atlas atlas in packer.Atlasses)
    {
        string atlasName = Path.Combine(packDir, $"{prefix}{atlasCount:000}.png");
        using MagickImage atlasImage = TextureWorker.ReadBGRAImageFromFile(atlasName);
        IPixelCollection<byte> atlasPixels = atlasImage.GetPixels();

        UndertaleEmbeddedTexture texture = new();
        texture.Name = new UndertaleString($"Texture {++lastTextPage}");
        texture.TextureData.Image = GMImage.FromMagickImage(atlasImage).ConvertToPng();
        Data.EmbeddedTextures.Add(texture);

        foreach (Node n in atlas.Nodes)
        {
            if (n.Texture != null)
            {

                UndertaleTexturePageItem texturePageItem = new();
                texturePageItem.Name = new UndertaleString($"PageItem {++lastTextPageItem}");
                texturePageItem.SourceX = (ushort)n.Bounds.X;
                texturePageItem.SourceY = (ushort)n.Bounds.Y;
                texturePageItem.SourceWidth = (ushort)n.Bounds.Width;
                texturePageItem.SourceHeight = (ushort)n.Bounds.Height;
                texturePageItem.TargetX = (ushort)n.Texture.TargetX;
                texturePageItem.TargetY = (ushort)n.Texture.TargetY;
                texturePageItem.TargetWidth = (ushort)n.Bounds.Width;
                texturePageItem.TargetHeight = (ushort)n.Bounds.Height;
                texturePageItem.BoundingWidth = (ushort)n.Texture.BoundingWidth;
                texturePageItem.BoundingHeight = (ushort)n.Texture.BoundingHeight;
                texturePageItem.TexturePage = texture;


                Data.TexturePageItems.Add(texturePageItem);


                string sourceFileName = Path.GetFileName(n.Texture.Source);
                string stripped = Path.GetFileNameWithoutExtension(sourceFileName);

                SpriteType spriteType = GetSpriteType(n.Texture.Source);
                if (importAsSprite)
                {
                    if (spriteType == SpriteType.Unknown || spriteType == SpriteType.Font)
                    {
                        spriteType = SpriteType.Sprite;
                    }
                }

                if (spriteType == SpriteType.Background)
                {
                    UndertaleBackground background = Data.Backgrounds.ByName(stripped);
                    if (background != null)
                    {
                        background.Texture = texturePageItem;
                    }
                    else
                    {

                        UndertaleString backgroundUTString = Data.Strings.MakeString(stripped);
                        UndertaleBackground newBackground = new();
                        newBackground.Name = backgroundUTString;
                        newBackground.Transparent = false;
                        newBackground.Preload = false;
                        newBackground.Texture = texturePageItem;
                        Data.Backgrounds.Add(newBackground);
                    }
                }
                else if (spriteType == SpriteType.Sprite)
                {

                    string spriteName;
                    int frame = 0;
                    try
                    {
                        var spriteParts = sprFrameRegex.Match(stripped);
                        spriteName = spriteParts.Groups[1].Value;
                        Int32.TryParse(spriteParts.Groups[2].Value, out frame);
                    }
                    catch (Exception e)
                    {
                        ScriptMessage($"Error: Image {stripped} has an invalid name. Skipping...");
                        continue;
                    }


                    UndertaleSprite.TextureEntry texentry = new();
                    texentry.Texture = texturePageItem;

                    
                    var frameData = TryGetTextureFrameData(spritesPath, spriteName);
                    if (frameData != null)
                    {
                        ApplyTextureFrameProperties(texturePageItem, spriteName, frame, frameData);
                    }


					UndertaleSprite sprite = Data.Sprites.ByName(spriteName);
					if (sprite is null)
					{
						UndertaleString spriteUTString = Data.Strings.MakeString(spriteName);
						UndertaleSprite newSprite = new();
						newSprite.Name        = spriteUTString;
						newSprite.Width       = (uint)n.Texture.BoundingWidth;
						newSprite.Height      = (uint)n.Texture.BoundingHeight;
						newSprite.MarginLeft  = n.Texture.TargetX;
						newSprite.MarginRight = n.Texture.TargetX + n.Bounds.Width - 1;
						newSprite.MarginTop   = n.Texture.TargetY;
						newSprite.MarginBottom= n.Texture.TargetY + n.Bounds.Height - 1;
						newSprite.OriginX = 0;
						newSprite.OriginY = 0;

						
						JsonElement? spriteMeta = TryLoadSpriteMetadata(spritesPath, spriteName);
						if (spriteMeta.HasValue)
						{
							ApplySpriteMetadata(newSprite, spriteMeta.Value);
						}

						if (frame > 0)
						{
							for (int i = 0; i < frame; i++)
								newSprite.Textures.Add(null);
						}


						if (!noMasksForBasicRectangles ||
							newSprite.SepMasks is not (UndertaleSprite.SepMaskType.AxisAlignedRect or UndertaleSprite.SepMaskType.RotatedRect))
						{
							
							if (newSprite.CollisionMasks.Count == 0)
							{
								maskNodes.Add(newSprite, n);
							}
						}

						newSprite.Textures.Add(texentry);
						Data.Sprites.Add(newSprite);
						continue;
					}






					if (frame >= sprite.Textures.Count)
					{
						while (frame >= sprite.Textures.Count)
							sprite.Textures.Add(null);
					}


					UndertaleTexturePageItem oldTex =
						(sprite.Textures[frame]?.Texture)
						?? sprite.Textures.FirstOrDefault(te => te != null)?.Texture;



					if (oldTex != null)
					{
						texturePageItem.TargetX        = oldTex.TargetX;
						texturePageItem.TargetY        = oldTex.TargetY;
						texturePageItem.TargetWidth    = oldTex.TargetWidth;
						texturePageItem.TargetHeight   = oldTex.TargetHeight;
						texturePageItem.BoundingWidth  = oldTex.BoundingWidth;
						texturePageItem.BoundingHeight = oldTex.BoundingHeight;
					}

					
					
					if (frameData != null)
					{
						ApplyTextureFrameProperties(texturePageItem, spriteName, frame, frameData);
					}

					
					
					JsonElement? existingSpriteMeta = TryLoadSpriteMetadata(spritesPath, spriteName);
					if (existingSpriteMeta.HasValue)
					{
						ApplySpriteMetadata(sprite, existingSpriteMeta.Value);
					}

					sprite.Textures[frame] = texentry;






					bool needMaskInit =
						sprite.SepMasks is UndertaleSprite.SepMaskType.Precise &&
						sprite.CollisionMasks.Count == 0;

					if (needMaskInit)
					{
						maskNodes[sprite] = n;
					}
				}
		   }
        }


            foreach ((UndertaleSprite maskSpr, Node maskNode) in maskNodes)
            {
                maskSpr.CollisionMasks.Clear();
                maskSpr.CollisionMasks.Add(maskSpr.NewMaskEntry(Data));
                (int maskWidth, int maskHeight) = maskSpr.CalculateMaskDimensions(Data);
                int maskStride = ((maskWidth + 7) / 8) * 8;

                BitArray maskingBitArray = new BitArray(maskStride * maskHeight);
                for (int y = 0; y < maskHeight && y < maskNode.Bounds.Height; y++)
                {
                    for (int x = 0; x < maskWidth && x < maskNode.Bounds.Width; x++)
                    {
                        IMagickColor<byte> pixelColor = atlasPixels.GetPixel(x + maskNode.Bounds.X, y + maskNode.Bounds.Y).ToColor();
                        if (bboxMasks)
                            maskingBitArray[(y * maskStride) + x] = (pixelColor.A > 0);
                        else
                            maskingBitArray[((y + maskNode.Texture.TargetY) * maskStride) + x + maskNode.Texture.TargetX] = (pixelColor.A > 0);
                    }
                }
                BitArray tempBitArray = new BitArray(maskingBitArray.Length);
                for (int i = 0; i < maskingBitArray.Length; i += 8)
                    for (int j = 0; j < 8; j++)
                        tempBitArray[j + i] = maskingBitArray[-(j - 7) + i];

                int numBytes = maskingBitArray.Length / 8;
                byte[] bytes = new byte[numBytes];
                tempBitArray.CopyTo(bytes, 0);
                for (int i = 0; i < bytes.Length; i++)
                    maskSpr.CollisionMasks[0].Data[i] = bytes[i];
            }
            maskNodes.Clear();


            atlasCount++;
    }

        HideProgressBar();
        ScriptMessage("Import Complete!");
}
finally
{
    foreach (MagickImage img in imagesToCleanup)
        img.Dispose();
}

public class TextureInfo
{
    public string Source;
    public int Width;
    public int Height;
    public int TargetX;
    public int TargetY;
    public int BoundingWidth;
    public int BoundingHeight;
    public MagickImage Image;
}

public enum SpriteType
{
    Sprite,
    Background,
    Font,
    Unknown
}


public enum SplitType
{
    Horizontal,
    Vertical,
}

public enum BestFitHeuristic
{
    Area,
    MaxOneAxis,
}

public struct Rect
{
    public int X { get; set; }
    public int Y { get; set; }
    public int Width { get; set; }
    public int Height { get; set; }
}

public class Node
{
    public Rect Bounds;
    public TextureInfo Texture;
    public SplitType SplitType;
}

public class Atlas
{
    public int Width;
    public int Height;
    public List<Node> Nodes;
}

public class Packer
{
    public List<TextureInfo> SourceTextures;
    public StringWriter Log;
    public StringWriter Error;
    public int Padding;
    public int AtlasSize;
    public bool DebugMode;
    public BestFitHeuristic FitHeuristic;
    public List<Atlas> Atlasses;

    public Packer()
    {
        SourceTextures = new List<TextureInfo>();
        Log = new StringWriter();
        Error = new StringWriter();
    }

    public void Process(string _SourceDir, string _Pattern, int _AtlasSize, int _Padding, bool _DebugMode)
    {
        Padding = _Padding;
        AtlasSize = _AtlasSize;
        DebugMode = _DebugMode;

        ScanForTextures(_SourceDir, _Pattern);
        List<TextureInfo> textures = new List<TextureInfo>();
        textures = SourceTextures.ToList();

        Atlasses = new List<Atlas>();
        while (textures.Count > 0)
        {
            Atlas atlas = new Atlas();
            atlas.Width = _AtlasSize;
            atlas.Height = _AtlasSize;
            List<TextureInfo> leftovers = LayoutAtlas(textures, atlas);
            if (leftovers.Count == 0)
            {

                while (leftovers.Count == 0)
                {
                    atlas.Width /= 2;
                    atlas.Height /= 2;
                    leftovers = LayoutAtlas(textures, atlas);
                }


                if (atlas.Width == 0)
                {
                    atlas.Width = 1;
                }
                else
                {
                    atlas.Width *= 2;
                }
                if (atlas.Height == 0)
                {
                    atlas.Height = 1;
                }
                else
                {
                    atlas.Height *= 2;
                }
                leftovers = LayoutAtlas(textures, atlas);
            }
            Atlasses.Add(atlas);
            textures = leftovers;
        }
    }

    public void SaveAtlasses(string _Destination)
    {
        int atlasCount = 0;
        string prefix = _Destination.Replace(Path.GetExtension(_Destination), "");
        string descFile = _Destination;

        StreamWriter tw = new StreamWriter(_Destination);
        tw.WriteLine("source_tex, atlas_tex, x, y, width, height");
        foreach (Atlas atlas in Atlasses)
        {
            string atlasName = $"{prefix}{atlasCount:000}.png";


            using (MagickImage img = CreateAtlasImage(atlas))
                TextureWorker.SaveImageToFile(img, atlasName);


            foreach (Node n in atlas.Nodes)
            {
                if (n.Texture != null)
                {
                    tw.Write(n.Texture.Source + ", ");
                    tw.Write(atlasName + ", ");
                    tw.Write((n.Bounds.X).ToString() + ", ");
                    tw.Write((n.Bounds.Y).ToString() + ", ");
                    tw.Write((n.Bounds.Width).ToString() + ", ");
                    tw.WriteLine((n.Bounds.Height).ToString());
                }
            }
            ++atlasCount;
        }
        tw.Close();
        tw = new StreamWriter(prefix + ".log");
        tw.WriteLine("--- LOG -------------------------------------------");
        tw.WriteLine(Log.ToString());
        tw.WriteLine("--- ERROR -----------------------------------------");
        tw.WriteLine(Error.ToString());
        tw.Close();
    }

    private void ScanForTextures(string _Path, string _Wildcard)
    {
        DirectoryInfo di = new(_Path);
        FileInfo[] files = di.GetFiles(_Wildcard, SearchOption.AllDirectories);
        foreach (FileInfo fi in files)
        {
            (int width, int height) = TextureWorker.GetImageSizeFromFile(fi.FullName);
            if (width == -1 || height == -1)
                continue;

            if (width <= AtlasSize && height <= AtlasSize)
            {
                TextureInfo ti = new();

                MagickReadSettings settings = new()
                {
                    ColorSpace = ColorSpace.sRGB,
                };
                MagickImage img = new(fi.FullName);
                imagesToCleanup.Add(img);

                ti.Source = fi.FullName;
                ti.BoundingWidth = (int)img.Width;
                ti.BoundingHeight = (int)img.Height;


                ti.TargetX = 0;
                ti.TargetY = 0;
                if (GetSpriteType(ti.Source) != SpriteType.Background)
                {
                    img.BorderColor = MagickColors.Transparent;
                    img.BackgroundColor = MagickColors.Transparent;
                    img.Border(1);
                    IMagickGeometry? bbox = img.BoundingBox;
                    if (bbox is not null)
                    {
                        ti.TargetX = bbox.X - 1;
                        ti.TargetY = bbox.Y - 1;


                        img.Trim();
                    }
                    else
                    {

                        ti.TargetX = 0;
                        ti.TargetY = 0;
                        img.Crop(1, 1);
                    }
                    img.ResetPage();
                }
                ti.Width = (int)img.Width;
                ti.Height = (int)img.Height;
                ti.Image = img;

                SourceTextures.Add(ti);

                Log.WriteLine($"Added {fi.FullName}");
            }
            else
            {
                Error.WriteLine($"{fi.FullName} is too large to fix in the atlas. Skipping!");
            }
        }
    }

    private void HorizontalSplit(Node _ToSplit, int _Width, int _Height, List<Node> _List)
    {
        Node n1 = new Node();
        n1.Bounds.X = _ToSplit.Bounds.X + _Width + Padding;
        n1.Bounds.Y = _ToSplit.Bounds.Y;
        n1.Bounds.Width = _ToSplit.Bounds.Width - _Width - Padding;
        n1.Bounds.Height = _Height;
        n1.SplitType = SplitType.Vertical;
        Node n2 = new Node();
        n2.Bounds.X = _ToSplit.Bounds.X;
        n2.Bounds.Y = _ToSplit.Bounds.Y + _Height + Padding;
        n2.Bounds.Width = _ToSplit.Bounds.Width;
        n2.Bounds.Height = _ToSplit.Bounds.Height - _Height - Padding;
        n2.SplitType = SplitType.Horizontal;
        if (n1.Bounds.Width > 0 && n1.Bounds.Height > 0)
            _List.Add(n1);
        if (n2.Bounds.Width > 0 && n2.Bounds.Height > 0)
            _List.Add(n2);
    }

    private void VerticalSplit(Node _ToSplit, int _Width, int _Height, List<Node> _List)
    {
        Node n1 = new Node();
        n1.Bounds.X = _ToSplit.Bounds.X + _Width + Padding;
        n1.Bounds.Y = _ToSplit.Bounds.Y;
        n1.Bounds.Width = _ToSplit.Bounds.Width - _Width - Padding;
        n1.Bounds.Height = _ToSplit.Bounds.Height;
        n1.SplitType = SplitType.Vertical;
        Node n2 = new Node();
        n2.Bounds.X = _ToSplit.Bounds.X;
        n2.Bounds.Y = _ToSplit.Bounds.Y + _Height + Padding;
        n2.Bounds.Width = _Width;
        n2.Bounds.Height = _ToSplit.Bounds.Height - _Height - Padding;
        n2.SplitType = SplitType.Horizontal;
        if (n1.Bounds.Width > 0 && n1.Bounds.Height > 0)
            _List.Add(n1);
        if (n2.Bounds.Width > 0 && n2.Bounds.Height > 0)
            _List.Add(n2);
    }

    private TextureInfo FindBestFitForNode(Node _Node, List<TextureInfo> _Textures)
    {
        TextureInfo bestFit = null;
        float nodeArea = _Node.Bounds.Width * _Node.Bounds.Height;
        float maxCriteria = 0.0f;
        foreach (TextureInfo ti in _Textures)
        {
            switch (FitHeuristic)
            {

                case BestFitHeuristic.MaxOneAxis:
                    if (ti.Width <= _Node.Bounds.Width && ti.Height <= _Node.Bounds.Height)
                    {
                        float wRatio = (float)ti.Width / (float)_Node.Bounds.Width;
                        float hRatio = (float)ti.Height / (float)_Node.Bounds.Height;
                        float ratio = wRatio > hRatio ? wRatio : hRatio;
                        if (ratio > maxCriteria)
                        {
                            maxCriteria = ratio;
                            bestFit = ti;
                        }
                    }
                    break;

                case BestFitHeuristic.Area:
                    if (ti.Width <= _Node.Bounds.Width && ti.Height <= _Node.Bounds.Height)
                    {
                        float textureArea = ti.Width * ti.Height;
                        float coverage = textureArea / nodeArea;
                        if (coverage > maxCriteria)
                        {
                            maxCriteria = coverage;
                            bestFit = ti;
                        }
                    }
                    break;
            }
        }
        return bestFit;
    }

    private List<TextureInfo> LayoutAtlas(List<TextureInfo> _Textures, Atlas _Atlas)
    {
        List<Node> freeList = new List<Node>();
        List<TextureInfo> textures = new List<TextureInfo>();
        _Atlas.Nodes = new List<Node>();
        textures = _Textures.ToList();
        Node root = new Node();
        root.Bounds.Width = _Atlas.Width;
        root.Bounds.Height = _Atlas.Height;
        root.SplitType = SplitType.Horizontal;
        freeList.Add(root);
        while (freeList.Count > 0 && textures.Count > 0)
        {
            Node node = freeList[0];
            freeList.RemoveAt(0);
            TextureInfo bestFit = FindBestFitForNode(node, textures);
            if (bestFit != null)
            {
                if (node.SplitType == SplitType.Horizontal)
                {
                    HorizontalSplit(node, bestFit.Width, bestFit.Height, freeList);
                }
                else
                {
                    VerticalSplit(node, bestFit.Width, bestFit.Height, freeList);
                }
                node.Texture = bestFit;
                node.Bounds.Width = bestFit.Width;
                node.Bounds.Height = bestFit.Height;
                textures.Remove(bestFit);
            }
            _Atlas.Nodes.Add(node);
        }
        return textures;
    }

    private MagickImage CreateAtlasImage(Atlas _Atlas)
    {
        MagickImage img = new(MagickColors.Transparent, (uint)_Atlas.Width, (uint)_Atlas.Height);

        foreach (Node n in _Atlas.Nodes)
        {
            if (n.Texture is not null)
            {
                MagickImage sourceImg = n.Texture.Image;
                using IMagickImage<byte> resizedSourceImg = TextureWorker.ResizeImage(sourceImg, n.Bounds.Width, n.Bounds.Height);
                img.Composite(resizedSourceImg, n.Bounds.X, n.Bounds.Y, CompositeOperator.Copy);
            }
        }

        return img;
    }
}

public static SpriteType GetSpriteType(string path)
{
    string folderPath = Path.GetDirectoryName(path);
    string folderName = new DirectoryInfo(folderPath).Name;
    string lowerName = folderName.ToLower();

    if (lowerName == "backgrounds" || lowerName == "background")
    {
        return SpriteType.Background;
    }
    else if (lowerName == "fonts" || lowerName == "font")
    {
        return SpriteType.Font;
    }
    else if (lowerName == "sprites" || lowerName == "sprite")
    {
        return SpriteType.Sprite;
    }
    return SpriteType.Unknown;
}

string CheckValidity()
{
    string importFolder = null;



    string dataWinDir = Path.GetDirectoryName(FilePath);


    if (dataWinDir.Contains("DeltahubMergeWorkspace"))
    {

        string objectsPath = Path.Combine(dataWinDir, "Objects");
        if (Directory.Exists(objectsPath))
        {
            importFolder = objectsPath;
            ScriptMessage($"Detected DELTAHUB context: {importFolder}");
            return importFolder;
        }
    }


    string objectsRelative = Path.Combine(dataWinDir, "Objects");
    if (Directory.Exists(objectsRelative))
    {
        importFolder = objectsRelative;
        ScriptMessage($"Found Objects folder relative to data.win: {importFolder}");
        return importFolder;
    }


    ScriptMessage("Could not automatically detect DELTAHUB Objects folder.");
    ScriptMessage("Please select the Objects folder containing sprites to import");
    importFolder = PromptChooseDirectory();

    if (string.IsNullOrWhiteSpace(importFolder))
        throw new ScriptException("No folder selected. Import cancelled.");

    ScriptMessage($"Using import folder: {importFolder}");
    return importFolder;
}