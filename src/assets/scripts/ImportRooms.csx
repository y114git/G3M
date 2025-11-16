

using System;
using System.IO;
using System.Text;
using System.Linq;
using System.Collections.Generic;
using System.Text.RegularExpressions;
using System.Reflection;
using UndertaleModLib;
using UndertaleModLib.Models;

void PrintLine(string s) => Console.WriteLine(s);
bool DEBUG = Environment.GetEnvironmentVariable("DELTAHUB_DEBUG") == "1";
void DebugLog(string s) { if (DEBUG) PrintLine($"[DEBUG] {s}"); }

string ReadAllTextSafe(string path)
{
    try { return File.ReadAllText(path, Encoding.UTF8); } catch { return null; }
}

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




string inputRoot = null;
if (!string.IsNullOrEmpty(FilePath))
{
    string dataWinDir = Path.GetDirectoryName(FilePath);
    string objectsNextToDataWin = Path.Combine(dataWinDir, "Objects");
    if (Directory.Exists(objectsNextToDataWin))
    {
        inputRoot = objectsNextToDataWin;
        Console.WriteLine($"[ImportRooms] Using Objects directory next to data.win: {inputRoot}");
    }
}


if (inputRoot == null)
{
    if (string.IsNullOrWhiteSpace(chapterNo) || string.IsNullOrWhiteSpace(modNo))
        throw new ScriptException("chapterNumber/modNumbersCache missing in /output/Cache/running/.");

    string modRoot = Path.Combine(deltahubRoot, "output", "xDeltaCombiner", chapterNo, modNo);
    inputRoot = Path.Combine(modRoot, "Objects");
    Console.WriteLine($"[ImportRooms] Using Objects directory from modNumbersCache: {inputRoot}");
}

string roomsIn = Path.Combine(inputRoot, "Rooms");

if (!Directory.Exists(roomsIn))
{
    PrintLine("[ImportRooms] No Rooms directory found, skipping.");
    return;
}


string ExtractJsonString(string json, string key)
{
    var pattern = $"\"{key}\"\\s*:\\s*\"([^\"]*)\"";
    var match = Regex.Match(json, pattern);
    return match.Success ? match.Groups[1].Value : null;
}

string ExtractJsonStringOrNull(string json, string key)
{
    var pattern = $"\"{key}\"\\s*:\\s*(null|\"([^\"]*)\")";
    var match = Regex.Match(json, pattern);
    if (!match.Success) return null;
    if (match.Groups[1].Value == "null") return null;
    return match.Groups[2].Value;
}

int ExtractJsonInt(string json, string key, int defaultValue = 0)
{
    var pattern = $"\"{key}\"\\s*:\\s*(-?\\d+)";
    var match = Regex.Match(json, pattern);
    return match.Success ? int.Parse(match.Groups[1].Value) : defaultValue;
}

uint ExtractJsonUInt(string json, string key, uint defaultValue = 0)
{
    var pattern = $"\"{key}\"\\s*:\\s*(\\d+)";
    var match = Regex.Match(json, pattern);
    return match.Success ? uint.Parse(match.Groups[1].Value) : defaultValue;
}

float ExtractJsonFloat(string json, string key, float defaultValue = 0.0f)
{
    var pattern = $"\"{key}\"\\s*:\\s*(-?\\d+\\.?\\d*)";
    var match = Regex.Match(json, pattern);
    return match.Success ? float.Parse(match.Groups[1].Value) : defaultValue;
}

bool ExtractJsonBool(string json, string key, bool defaultValue = false)
{
    var pattern = $"\"{key}\"\\s*:\\s*(true|false)";
    var match = Regex.Match(json, pattern);
    if (!match.Success) return defaultValue;
    return match.Groups[1].Value == "true";
}


string ExtractJsonArray(string json, string key)
{
    var pattern = $"\"{key}\"\\s*:\\s*\\[([^\\]]*)\\]";
    var match = Regex.Match(json, pattern, RegexOptions.Singleline);
    return match.Success ? match.Groups[1].Value : "";
}


void ImportRoom(string filePath)
{
    string json = ReadAllTextSafe(filePath);
    if (string.IsNullOrEmpty(json))
    {
        PrintLine($"[ImportRooms] ERROR: Failed to read {filePath}");
        return;
    }
    
    string roomName = ExtractJsonString(json, "name");
    if (string.IsNullOrEmpty(roomName))
    {
        roomName = Path.GetFileNameWithoutExtension(filePath);
    }
    
    
    UndertaleRoom room = Data.Rooms.ByName(roomName);
    if (room == null)
    {
        room = new UndertaleRoom();
        room.Name = new UndertaleString(roomName);
        Data.Strings.Add(room.Name);
        Data.Rooms.Add(room);
        PrintLine($"[ImportRooms] Created new room: {roomName}");
    }
    else
    {
        PrintLine($"[ImportRooms] Updating existing room: {roomName} (smart merge)");
        
        
        
    }
    
    
    room.Width = ExtractJsonUInt(json, "width", room.Width);
    room.Height = ExtractJsonUInt(json, "height", room.Height);
    room.Speed = ExtractJsonUInt(json, "speed", room.Speed);
    room.Persistent = ExtractJsonBool(json, "persistent", room.Persistent);
    int bgColor = ExtractJsonInt(json, "backgroundColor", 0);
    room.BackgroundColor = (uint)(0xFF000000 | bgColor);
    room.DrawBackgroundColor = ExtractJsonBool(json, "drawBackgroundColor", room.DrawBackgroundColor);
    string ccIdName = ExtractJsonStringOrNull(json, "creationCodeId");
    room.CreationCodeId = string.IsNullOrEmpty(ccIdName) ? null : Data.Code.ByName(ccIdName);
    room.Flags = (UndertaleRoom.RoomEntryFlags)ExtractJsonInt(json, "flags", (int)room.Flags);
    room.World = ExtractJsonBool(json, "world", room.World);
    room.Top = ExtractJsonUInt(json, "top", room.Top);
    room.Left = ExtractJsonUInt(json, "left", room.Left);
    room.Right = ExtractJsonUInt(json, "right", room.Right);
    room.Bottom = ExtractJsonUInt(json, "bottom", room.Bottom);
    room.GravityX = ExtractJsonFloat(json, "gravityX", room.GravityX);
    room.GravityY = ExtractJsonFloat(json, "gravityY", room.GravityY);
    room.MetersPerPixel = ExtractJsonFloat(json, "metersPerPixel", room.MetersPerPixel);
    
    
    string backgroundsJson = ExtractJsonArray(json, "backgrounds");
    if (!string.IsNullOrEmpty(backgroundsJson))
    {
        
        room.Backgrounds.Clear();
        var bgMatches = Regex.Matches(backgroundsJson, "\\{[^}]*\\}", RegexOptions.Singleline);
        foreach (Match bgMatch in bgMatches)
        {
            string bgJson = bgMatch.Value;
            var bg = new UndertaleRoom.Background();
            bg.ParentRoom = room;
            bg.Enabled = ExtractJsonBool(bgJson, "enabled", true);
            bg.Foreground = ExtractJsonBool(bgJson, "foreground", false);
            string bgDefName = ExtractJsonStringOrNull(bgJson, "backgroundDefinition");
            bg.BackgroundDefinition = string.IsNullOrEmpty(bgDefName) ? null : Data.Backgrounds.ByName(bgDefName);
            bg.X = ExtractJsonInt(bgJson, "x", 0);
            bg.Y = ExtractJsonInt(bgJson, "y", 0);
            bg.TiledHorizontally = ExtractJsonBool(bgJson, "tiledHorizontally", false);
            bg.TiledVertically = ExtractJsonBool(bgJson, "tiledVertically", false);
            bg.SpeedX = ExtractJsonInt(bgJson, "speedX", 0);
            bg.SpeedY = ExtractJsonInt(bgJson, "speedY", 0);
            bg.Stretch = ExtractJsonBool(bgJson, "stretch", false);
            room.Backgrounds.Add(bg);
        }
    }
    
    
    
    string viewsJson = ExtractJsonArray(json, "views");
    if (!string.IsNullOrEmpty(viewsJson))
    {
        room.Views.Clear();
        var viewMatches = Regex.Matches(viewsJson, "\\{[^}]*\\}", RegexOptions.Singleline);
        foreach (Match viewMatch in viewMatches)
        {
            string viewJson = viewMatch.Value;
            var view = new UndertaleRoom.View();
            view.Enabled = ExtractJsonBool(viewJson, "enabled", false);
            view.ViewX = ExtractJsonInt(viewJson, "viewX", 0);
            view.ViewY = ExtractJsonInt(viewJson, "viewY", 0);
            view.ViewWidth = ExtractJsonInt(viewJson, "viewWidth", 0);
            view.ViewHeight = ExtractJsonInt(viewJson, "viewHeight", 0);
            view.PortX = ExtractJsonInt(viewJson, "portX", 0);
            view.PortY = ExtractJsonInt(viewJson, "portY", 0);
            view.PortWidth = ExtractJsonInt(viewJson, "portWidth", 0);
            view.PortHeight = ExtractJsonInt(viewJson, "portHeight", 0);
            view.BorderX = ExtractJsonUInt(viewJson, "borderX", 0);
            view.BorderY = ExtractJsonUInt(viewJson, "borderY", 0);
            view.SpeedX = ExtractJsonInt(viewJson, "speedX", 0);
            view.SpeedY = ExtractJsonInt(viewJson, "speedY", 0);
            string objIdName = ExtractJsonStringOrNull(viewJson, "objectId");
            view.ObjectId = string.IsNullOrEmpty(objIdName) ? null : Data.GameObjects.ByName(objIdName);
            room.Views.Add(view);
        }
    }
    
    
    
    string gameObjectsJson = ExtractJsonArray(json, "gameObjects");
    if (!string.IsNullOrEmpty(gameObjectsJson))
    {
        
        var existingObjects = new Dictionary<uint, UndertaleRoom.GameObject>();
        foreach (var existingObj in room.GameObjects)
        {
            if (existingObj.InstanceID > 0)
                existingObjects[existingObj.InstanceID] = existingObj;
        }
        
        var objMatches = Regex.Matches(gameObjectsJson, "\\{[^}]*\\}", RegexOptions.Singleline);
        foreach (Match objMatch in objMatches)
        {
            string objJson = objMatch.Value;
            uint instanceID = ExtractJsonUInt(objJson, "instanceID", 0);
            
            UndertaleRoom.GameObject obj;
            if (instanceID > 0 && existingObjects.ContainsKey(instanceID))
            {
                
                obj = existingObjects[instanceID];
                PrintLine($"[ImportRooms] Updating existing GameObject instanceID={instanceID}");
            }
            else
            {
                
                obj = new UndertaleRoom.GameObject();
                room.GameObjects.Add(obj);
            }
            
            obj.X = ExtractJsonInt(objJson, "x", obj.X);
            obj.Y = ExtractJsonInt(objJson, "y", obj.Y);
            string objDefName = ExtractJsonStringOrNull(objJson, "objectDefinition");
            if (!string.IsNullOrEmpty(objDefName))
                obj.ObjectDefinition = Data.GameObjects.ByName(objDefName);
            if (instanceID > 0)
                obj.InstanceID = instanceID;
            string ccName = ExtractJsonStringOrNull(objJson, "creationCode");
            if (!string.IsNullOrEmpty(ccName))
                obj.CreationCode = Data.Code.ByName(ccName);
            obj.ScaleX = ExtractJsonFloat(objJson, "scaleX", obj.ScaleX);
            obj.ScaleY = ExtractJsonFloat(objJson, "scaleY", obj.ScaleY);
            int colorVal = ExtractJsonInt(objJson, "color", -1);
            if (colorVal >= 0)
                obj.Color = (uint)colorVal;
            obj.Rotation = ExtractJsonFloat(objJson, "rotation", obj.Rotation);
            string preCcName = ExtractJsonStringOrNull(objJson, "preCreateCode");
            if (!string.IsNullOrEmpty(preCcName))
                obj.PreCreateCode = Data.Code.ByName(preCcName);
            obj.ImageSpeed = ExtractJsonFloat(objJson, "imageSpeed", obj.ImageSpeed);
            obj.ImageIndex = ExtractJsonInt(objJson, "imageIndex", obj.ImageIndex);
        }
    }
    
    
    
    string tilesJson = ExtractJsonArray(json, "tiles");
    if (!string.IsNullOrEmpty(tilesJson))
    {
        room.Tiles.Clear();
        var tileMatches = Regex.Matches(tilesJson, "\\{[^}]*\\}", RegexOptions.Singleline);
        foreach (Match tileMatch in tileMatches)
        {
            string tileJson = tileMatch.Value;
            var tile = new UndertaleRoom.Tile();
            tile.spriteMode = ExtractJsonBool(tileJson, "spriteMode", false);
            tile.X = ExtractJsonInt(tileJson, "x", 0);
            tile.Y = ExtractJsonInt(tileJson, "y", 0);
            string bgDefName = ExtractJsonStringOrNull(tileJson, "backgroundDefinition");
            tile.BackgroundDefinition = string.IsNullOrEmpty(bgDefName) ? null : Data.Backgrounds.ByName(bgDefName);
            string sprDefName = ExtractJsonStringOrNull(tileJson, "spriteDefinition");
            tile.SpriteDefinition = string.IsNullOrEmpty(sprDefName) ? null : Data.Sprites.ByName(sprDefName);
            tile.SourceX = ExtractJsonInt(tileJson, "sourceX", 0);
            tile.SourceY = ExtractJsonInt(tileJson, "sourceY", 0);
            tile.Width = ExtractJsonUInt(tileJson, "width", 0);
            tile.Height = ExtractJsonUInt(tileJson, "height", 0);
            tile.TileDepth = ExtractJsonInt(tileJson, "tileDepth", 0);
            tile.InstanceID = ExtractJsonUInt(tileJson, "instanceID", 0);
            tile.ScaleX = ExtractJsonFloat(tileJson, "scaleX", 1.0f);
            tile.ScaleY = ExtractJsonFloat(tileJson, "scaleY", 1.0f);
            tile.Color = (uint)ExtractJsonInt(tileJson, "color", unchecked((int)0xFFFFFFFF));
            room.Tiles.Add(tile);
        }
    }
    
    
    
    string layersJson = ExtractJsonArray(json, "layers");
    if (!string.IsNullOrEmpty(layersJson))
    {
        
        var existingLayers = new Dictionary<uint, UndertaleRoom.Layer>();
        foreach (var existingLayer in room.Layers)
        {
            if (existingLayer.LayerId > 0)
                existingLayers[existingLayer.LayerId] = existingLayer;
        }
        
        var layerMatches = Regex.Matches(layersJson, "\\{[^}]*\\}", RegexOptions.Singleline);
        foreach (Match layerMatch in layerMatches)
        {
            string layerJson = layerMatch.Value;
            uint layerId = ExtractJsonUInt(layerJson, "layerId", 0);
            
            UndertaleRoom.Layer layer;
            if (layerId > 0 && existingLayers.ContainsKey(layerId))
            {
                
                layer = existingLayers[layerId];
                PrintLine($"[ImportRooms] Updating existing Layer layerId={layerId}");
            }
            else
            {
                
                layer = new UndertaleRoom.Layer();
                layer.ParentRoom = room;
                room.Layers.Add(layer);
            }
            
            string layerName = ExtractJsonStringOrNull(layerJson, "layerName");
            if (!string.IsNullOrEmpty(layerName))
            {
                layer.LayerName = new UndertaleString(layerName);
                if (!Data.Strings.Any(s => s == layer.LayerName))
                    Data.Strings.Add(layer.LayerName);
            }
            if (layerId > 0)
                layer.LayerId = layerId;
            int layerType = ExtractJsonInt(layerJson, "layerType", -1);
            if (layerType >= 0)
                layer.LayerType = (UndertaleRoom.LayerType)layerType;
            layer.LayerDepth = ExtractJsonInt(layerJson, "layerDepth", layer.LayerDepth);
            layer.XOffset = ExtractJsonFloat(layerJson, "xOffset", layer.XOffset);
            layer.YOffset = ExtractJsonFloat(layerJson, "yOffset", layer.YOffset);
            layer.HSpeed = ExtractJsonFloat(layerJson, "hSpeed", layer.HSpeed);
            layer.VSpeed = ExtractJsonFloat(layerJson, "vSpeed", layer.VSpeed);
            bool isVisible = ExtractJsonBool(layerJson, "isVisible", layer.IsVisible);
            layer.IsVisible = isVisible;
            
            
            switch (layer.LayerType)
            {
                case UndertaleRoom.LayerType.Background:
                    ImportBackgroundLayerData(layer, layerJson);
                    break;
                case UndertaleRoom.LayerType.Instances:
                    ImportInstancesLayerData(layer, layerJson);
                    break;
                case UndertaleRoom.LayerType.Assets:
                    ImportAssetsLayerData(layer, layerJson);
                    break;
                case UndertaleRoom.LayerType.Tiles:
                    ImportTilesLayerData(layer, layerJson);
                    break;
            }
        }
    }
    
}


void ImportBackgroundLayerData(UndertaleRoom.Layer layer, string layerJson)
{
    try
    {
        string layerDataJson = ExtractJsonArray(layerJson, "layerData") ?? ExtractJsonString(layerJson, "layerData");
        if (string.IsNullOrEmpty(layerDataJson))
            return;
        
        var layerData = new UndertaleRoom.Layer.LayerBackgroundData();
        layerData.ParentLayer = layer;
        layerData.Visible = ExtractJsonBool(layerDataJson, "visible", true);
        layerData.Foreground = ExtractJsonBool(layerDataJson, "foreground", false);
        string spriteName = ExtractJsonStringOrNull(layerDataJson, "sprite");
        layerData.Sprite = string.IsNullOrEmpty(spriteName) ? null : Data.Sprites.ByName(spriteName);
        layerData.TiledHorizontally = ExtractJsonBool(layerDataJson, "tiledHorizontally", false);
        layerData.TiledVertically = ExtractJsonBool(layerDataJson, "tiledVertically", false);
        layerData.Stretch = ExtractJsonBool(layerDataJson, "stretch", false);
        int colorVal = ExtractJsonInt(layerDataJson, "color", -1);
        if (colorVal >= 0)
            layerData.Color = (uint)colorVal;
        layerData.FirstFrame = ExtractJsonFloat(layerDataJson, "firstFrame", 0.0f);
        layerData.AnimationSpeed = ExtractJsonFloat(layerDataJson, "animationSpeed", 0.0f);
        int animSpeedType = ExtractJsonInt(layerDataJson, "animationSpeedType", -1);
        if (animSpeedType >= 0)
            layerData.AnimationSpeedType = (AnimationSpeedType)animSpeedType;
        
        layer.Data = layerData;
    }
    catch (Exception e)
    {
        PrintLine($"[ImportRooms] ERROR: Failed to import Background layer data: {e.Message}");
    }
}


void ImportInstancesLayerData(UndertaleRoom.Layer layer, string layerJson)
{
    try
    {
        string layerDataJson = ExtractJsonArray(layerJson, "layerData") ?? ExtractJsonString(layerJson, "layerData");
        if (string.IsNullOrEmpty(layerDataJson))
            return;
        
        var layerData = new UndertaleRoom.Layer.LayerInstancesData();
        layerData.Instances = new UndertalePointerList<UndertaleRoom.GameObject>();
        
        string instancesJson = ExtractJsonArray(layerDataJson, "instances");
        if (!string.IsNullOrEmpty(instancesJson))
        {
            var instanceMatches = Regex.Matches(instancesJson, "\\{[^}]*\\}", RegexOptions.Singleline);
            foreach (Match instanceMatch in instanceMatches)
            {
                string instanceJson = instanceMatch.Value;
                var instance = new UndertaleRoom.GameObject();
                instance.X = ExtractJsonInt(instanceJson, "x", 0);
                instance.Y = ExtractJsonInt(instanceJson, "y", 0);
                string objDefName = ExtractJsonStringOrNull(instanceJson, "objectDefinition");
                instance.ObjectDefinition = string.IsNullOrEmpty(objDefName) ? null : Data.GameObjects.ByName(objDefName);
                instance.InstanceID = ExtractJsonUInt(instanceJson, "instanceID", 0);
                string ccName = ExtractJsonStringOrNull(instanceJson, "creationCode");
                instance.CreationCode = string.IsNullOrEmpty(ccName) ? null : Data.Code.ByName(ccName);
                instance.ScaleX = ExtractJsonFloat(instanceJson, "scaleX", 1.0f);
                instance.ScaleY = ExtractJsonFloat(instanceJson, "scaleY", 1.0f);
                int colorVal = ExtractJsonInt(instanceJson, "color", -1);
                if (colorVal >= 0)
                    instance.Color = (uint)colorVal;
                instance.Rotation = ExtractJsonFloat(instanceJson, "rotation", 0.0f);
                string preCcName = ExtractJsonStringOrNull(instanceJson, "preCreateCode");
                instance.PreCreateCode = string.IsNullOrEmpty(preCcName) ? null : Data.Code.ByName(preCcName);
                instance.ImageSpeed = ExtractJsonFloat(instanceJson, "imageSpeed", 1.0f);
                instance.ImageIndex = ExtractJsonInt(instanceJson, "imageIndex", 0);
                layerData.Instances.Add(instance);
            }
        }
        
        layer.Data = layerData;
    }
    catch (Exception e)
    {
        PrintLine($"[ImportRooms] ERROR: Failed to import Instances layer data: {e.Message}");
    }
}


void ImportAssetsLayerData(UndertaleRoom.Layer layer, string layerJson)
{
    try
    {
        string layerDataJson = ExtractJsonArray(layerJson, "layerData") ?? ExtractJsonString(layerJson, "layerData");
        if (string.IsNullOrEmpty(layerDataJson))
            return;
        
        var layerData = new UndertaleRoom.Layer.LayerAssetsData();
        layerData.LegacyTiles = new UndertalePointerList<UndertaleRoom.Tile>();
        layerData.Sprites = new UndertalePointerList<UndertaleRoom.SpriteInstance>();
        layerData.Sequences = new UndertalePointerList<UndertaleRoom.SequenceInstance>();
        layerData.NineSlices = new UndertalePointerList<UndertaleRoom.SpriteInstance>();
        
        
        string legacyTilesJson = ExtractJsonArray(layerDataJson, "legacyTiles");
        if (!string.IsNullOrEmpty(legacyTilesJson))
        {
            var tileMatches = Regex.Matches(legacyTilesJson, "\\{[^}]*\\}", RegexOptions.Singleline);
            foreach (Match tileMatch in tileMatches)
            {
                string tileJson = tileMatch.Value;
                var tile = new UndertaleRoom.Tile();
                tile.spriteMode = ExtractJsonBool(tileJson, "spriteMode", false);
                tile.X = ExtractJsonInt(tileJson, "x", 0);
                tile.Y = ExtractJsonInt(tileJson, "y", 0);
                string bgDefName = ExtractJsonStringOrNull(tileJson, "backgroundDefinition");
                tile.BackgroundDefinition = string.IsNullOrEmpty(bgDefName) ? null : Data.Backgrounds.ByName(bgDefName);
                string sprDefName = ExtractJsonStringOrNull(tileJson, "spriteDefinition");
                tile.SpriteDefinition = string.IsNullOrEmpty(sprDefName) ? null : Data.Sprites.ByName(sprDefName);
                tile.SourceX = ExtractJsonInt(tileJson, "sourceX", 0);
                tile.SourceY = ExtractJsonInt(tileJson, "sourceY", 0);
                tile.Width = ExtractJsonUInt(tileJson, "width", 0);
                tile.Height = ExtractJsonUInt(tileJson, "height", 0);
                tile.TileDepth = ExtractJsonInt(tileJson, "tileDepth", 0);
                tile.InstanceID = ExtractJsonUInt(tileJson, "instanceID", 0);
                tile.ScaleX = ExtractJsonFloat(tileJson, "scaleX", 1.0f);
                tile.ScaleY = ExtractJsonFloat(tileJson, "scaleY", 1.0f);
                int colorVal = ExtractJsonInt(tileJson, "color", -1);
                if (colorVal >= 0)
                    tile.Color = (uint)colorVal;
                layerData.LegacyTiles.Add(tile);
            }
        }
        
        
        string spritesJson = ExtractJsonArray(layerDataJson, "sprites");
        if (!string.IsNullOrEmpty(spritesJson))
        {
            var spriteMatches = Regex.Matches(spritesJson, "\\{[^}]*\\}", RegexOptions.Singleline);
            foreach (Match spriteMatch in spriteMatches)
            {
                string spriteJson = spriteMatch.Value;
                var sprite = new UndertaleRoom.SpriteInstance();
                sprite.X = ExtractJsonFloat(spriteJson, "x", 0.0f);
                sprite.Y = ExtractJsonFloat(spriteJson, "y", 0.0f);
                string sprDefName = ExtractJsonStringOrNull(spriteJson, "spriteDefinition");
                sprite.SpriteDefinition = string.IsNullOrEmpty(sprDefName) ? null : Data.Sprites.ByName(sprDefName);
                sprite.Color = (uint)ExtractJsonInt(spriteJson, "color", unchecked((int)0xFFFFFFFF));
                sprite.AnimationSpeed = ExtractJsonFloat(spriteJson, "animationSpeed", 1.0f);
                sprite.AnimationSpeedType = (AnimationSpeedType)ExtractJsonInt(spriteJson, "animationSpeedType", 0);
                sprite.FrameIndex = ExtractJsonInt(spriteJson, "frameIndex", 0);
                sprite.ScaleX = ExtractJsonFloat(spriteJson, "scaleX", 1.0f);
                sprite.ScaleY = ExtractJsonFloat(spriteJson, "scaleY", 1.0f);
                sprite.Rotation = ExtractJsonFloat(spriteJson, "rotation", 0.0f);
                layerData.Sprites.Add(sprite);
            }
        }
        
        
        string sequencesJson = ExtractJsonArray(layerDataJson, "sequences");
        if (!string.IsNullOrEmpty(sequencesJson))
        {
            var seqMatches = Regex.Matches(sequencesJson, "\\{[^}]*\\}", RegexOptions.Singleline);
            foreach (Match seqMatch in seqMatches)
            {
                
                
                PrintLine($"[ImportRooms] NOTE: Sequence import is simplified");
            }
        }
        
        
        string nineSlicesJson = ExtractJsonArray(layerDataJson, "nineSlices");
        if (!string.IsNullOrEmpty(nineSlicesJson))
        {
            var nineSliceMatches = Regex.Matches(nineSlicesJson, "\\{[^}]*\\}", RegexOptions.Singleline);
            foreach (Match nineSliceMatch in nineSliceMatches)
            {
                string nineSliceJson = nineSliceMatch.Value;
                var nineSlice = new UndertaleRoom.SpriteInstance();
                nineSlice.X = ExtractJsonFloat(nineSliceJson, "x", 0.0f);
                nineSlice.Y = ExtractJsonFloat(nineSliceJson, "y", 0.0f);
                string sprDefName = ExtractJsonStringOrNull(nineSliceJson, "spriteDefinition");
                nineSlice.SpriteDefinition = string.IsNullOrEmpty(sprDefName) ? null : Data.Sprites.ByName(sprDefName);
                nineSlice.Color = (uint)ExtractJsonInt(nineSliceJson, "color", unchecked((int)0xFFFFFFFF));
                nineSlice.AnimationSpeed = ExtractJsonFloat(nineSliceJson, "animationSpeed", 1.0f);
                nineSlice.AnimationSpeedType = (AnimationSpeedType)ExtractJsonInt(nineSliceJson, "animationSpeedType", 0);
                nineSlice.FrameIndex = ExtractJsonInt(nineSliceJson, "frameIndex", 0);
                nineSlice.ScaleX = ExtractJsonFloat(nineSliceJson, "scaleX", 1.0f);
                nineSlice.ScaleY = ExtractJsonFloat(nineSliceJson, "scaleY", 1.0f);
                nineSlice.Rotation = ExtractJsonFloat(nineSliceJson, "rotation", 0.0f);
                layerData.NineSlices.Add(nineSlice);
            }
        }
        
        layer.Data = layerData;
    }
    catch (Exception e)
    {
        PrintLine($"[ImportRooms] ERROR: Failed to import Assets layer data: {e.Message}");
        PrintLine($"[ImportRooms] Stack trace: {e.StackTrace}");
    }
}


void ImportTilesLayerData(UndertaleRoom.Layer layer, string layerJson)
{
    try
    {
        string layerDataJson = ExtractJsonArray(layerJson, "layerData") ?? ExtractJsonString(layerJson, "layerData");
        if (string.IsNullOrEmpty(layerDataJson))
            return;
        
        var layerData = new UndertaleRoom.Layer.LayerTilesData();
        string backgroundName = ExtractJsonStringOrNull(layerDataJson, "background");
        layerData.Background = string.IsNullOrEmpty(backgroundName) ? null : Data.Backgrounds.ByName(backgroundName);
        layerData.TilesX = ExtractJsonUInt(layerDataJson, "tilesX", 0);
        layerData.TilesY = ExtractJsonUInt(layerDataJson, "tilesY", 0);
        
        
        string tileDataJson = ExtractJsonArray(layerDataJson, "tileData");
        if (!string.IsNullOrEmpty(tileDataJson))
        {
            
            var rowMatches = Regex.Matches(tileDataJson, "\\[([^\\]]*)\\]", RegexOptions.Singleline);
            uint[][] tileIds = new uint[layerData.TilesY][];
            for (int y = 0; y < layerData.TilesY && y < rowMatches.Count; y++)
            {
                tileIds[y] = new uint[layerData.TilesX];
                string rowJson = rowMatches[y].Groups[1].Value;
                var cellMatches = Regex.Matches(rowJson, "\\{[^}]*\\}", RegexOptions.Singleline);
                for (int x = 0; x < layerData.TilesX && x < cellMatches.Count; x++)
                {
                    string cellJson = cellMatches[x].Value;
                    tileIds[y][x] = ExtractJsonUInt(cellJson, "id", 0);
                }
            }
            layerData.TileData = tileIds;
        }
        
        layer.Data = layerData;
    }
    catch (Exception e)
    {
        PrintLine($"[ImportRooms] ERROR: Failed to import Tiles layer data: {e.Message}");
        PrintLine($"[ImportRooms] Stack trace: {e.StackTrace}");
    }
}


int roomsImported = 0;
int roomsUpdated = 0;

if (Directory.Exists(roomsIn))
{
    var roomFiles = Directory.GetFiles(roomsIn, "*.json");
    foreach (var roomFile in roomFiles)
    {
        try
        {
            bool roomExisted = Data.Rooms.ByName(Path.GetFileNameWithoutExtension(roomFile)) != null;
            ImportRoom(roomFile);
            if (roomExisted) roomsUpdated++; else roomsImported++;
        }
        catch (Exception e)
        {
            PrintLine($"[ImportRooms] ERROR: Failed to import {roomFile}: {e.Message}");
        }
    }
}


Data.SaveFile(Data.FilePath);

PrintLine($"\n[ImportRooms] Summary for Mod {modNo}:");
PrintLine($"  Rooms - Imported: {roomsImported}, Updated: {roomsUpdated}");
PrintLine("[ImportRooms] Done.");

