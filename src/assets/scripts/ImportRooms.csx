#load "SharedPaths.csx"

using System;
using System.IO;
using System.Text;
using System.Linq;
using System.Collections.Generic;
using System.Text.Json;
using UndertaleModLib;
using UndertaleModLib.Models;
using UndertaleModLib.Util;

EnsureDataLoaded();

void PrintLine(string s) => Console.WriteLine(s);

ImportContext ctx = PrepareImportContext();
string roomsDir = Path.Combine(ctx.InputRoot, "Rooms");

if (!Directory.Exists(roomsDir))
{
    PrintLine("[ImportRooms] Rooms directory not found, skipping import.");
    return;
}

string[] roomFiles = Directory.GetFiles(roomsDir, "*.json");
if (roomFiles.Length == 0)
{
    PrintLine("[ImportRooms] No room JSON files found, skipping import.");
    return;
}

PrintLine($"[ImportRooms] Found {roomFiles.Length} room file(s) to import.");

SetProgressBar(null, "Importing Rooms", 0, roomFiles.Length);
StartProgressBarUpdater();

foreach (string roomFile in roomFiles)
{
    try
    {
        string jsonContent = File.ReadAllText(roomFile, Encoding.UTF8);
        string roomName = Path.GetFileNameWithoutExtension(roomFile);
        
        
        JsonDocument jsonDoc = JsonDocument.Parse(jsonContent);
        JsonElement root = jsonDoc.RootElement;
        
        
        UndertaleRoom room = Data.Rooms.ByName(roomName);
        if (room == null)
        {
            
            room = new UndertaleRoom();
            room.Name = Data.Strings.MakeString(roomName);
            Data.Rooms.Add(room);
            PrintLine($"[ImportRooms] Created new room: {roomName}");
        }
        else
        {
            PrintLine($"[ImportRooms] Updating existing room: {roomName}");
        }
        
        
        UpdateRoomFromJson(room, root);
        
        jsonDoc.Dispose();
        IncrementProgress();
    }
    catch (Exception ex)
    {
        PrintLine($"[ImportRooms] Error importing room {Path.GetFileName(roomFile)}: {ex.Message}");
    }
}

await StopProgressBarUpdater();
HideProgressBar();

PrintLine("[ImportRooms] Room import completed.");

void UpdateRoomFromJson(UndertaleRoom room, JsonElement data)
{
    
    if (data.TryGetProperty("caption", out JsonElement captionElm) && captionElm.ValueKind == JsonValueKind.String)
        room.Caption = Data.Strings.MakeString(captionElm.GetString());
    
    if (data.TryGetProperty("width", out JsonElement widthElm) && widthElm.ValueKind == JsonValueKind.Number)
        room.Width = (uint)Math.Max(0, widthElm.GetInt32());
    
    if (data.TryGetProperty("height", out JsonElement heightElm) && heightElm.ValueKind == JsonValueKind.Number)
        room.Height = (uint)Math.Max(0, heightElm.GetInt32());
    
    if (data.TryGetProperty("speed", out JsonElement speedElm) && speedElm.ValueKind == JsonValueKind.Number)
        room.Speed = (uint)Math.Max(0, speedElm.GetInt32());
    
    if (data.TryGetProperty("persistent", out JsonElement persistentElm) && persistentElm.ValueKind == JsonValueKind.True || persistentElm.ValueKind == JsonValueKind.False)
        room.Persistent = persistentElm.GetBoolean();
    
    if (data.TryGetProperty("backgroundColor", out JsonElement bgColorElm) && bgColorElm.ValueKind == JsonValueKind.Number)
        room.BackgroundColor = (uint)bgColorElm.GetInt32();
    
    if (data.TryGetProperty("drawBackgroundColor", out JsonElement drawBgElm) && (drawBgElm.ValueKind == JsonValueKind.True || drawBgElm.ValueKind == JsonValueKind.False))
        room.DrawBackgroundColor = drawBgElm.GetBoolean();
    
    if (data.TryGetProperty("creationCodeId", out JsonElement codeIdElm) && codeIdElm.ValueKind == JsonValueKind.String)
    {
        string codeName = codeIdElm.GetString();
        if (!string.IsNullOrEmpty(codeName))
        {
            var code = Data.Code.ByName(codeName);
            if (code != null)
                room.CreationCodeId = code;
        }
    }
    
    if (data.TryGetProperty("flags", out JsonElement flagsElm) && flagsElm.ValueKind == JsonValueKind.Number)
        room.Flags = (UndertaleRoom.RoomEntryFlags)flagsElm.GetInt32();
    
    if (data.TryGetProperty("world", out JsonElement worldElm) && (worldElm.ValueKind == JsonValueKind.True || worldElm.ValueKind == JsonValueKind.False))
        room.World = worldElm.GetBoolean();
    
    if (data.TryGetProperty("top", out JsonElement topElm) && topElm.ValueKind == JsonValueKind.Number)
        room.Top = (uint)Math.Max(0, topElm.GetInt32());
    
    if (data.TryGetProperty("left", out JsonElement leftElm) && leftElm.ValueKind == JsonValueKind.Number)
        room.Left = (uint)Math.Max(0, leftElm.GetInt32());
    
    if (data.TryGetProperty("right", out JsonElement rightElm) && rightElm.ValueKind == JsonValueKind.Number)
        room.Right = (uint)Math.Max(0, rightElm.GetInt32());
    
    if (data.TryGetProperty("bottom", out JsonElement bottomElm) && bottomElm.ValueKind == JsonValueKind.Number)
        room.Bottom = (uint)Math.Max(0, bottomElm.GetInt32());
    
    if (data.TryGetProperty("gravityX", out JsonElement gxElm) && gxElm.ValueKind == JsonValueKind.Number)
        room.GravityX = (float)gxElm.GetDouble();
    
    if (data.TryGetProperty("gravityY", out JsonElement gyElm) && gyElm.ValueKind == JsonValueKind.Number)
        room.GravityY = (float)gyElm.GetDouble();
    
    if (data.TryGetProperty("metersPerPixel", out JsonElement mppElm) && mppElm.ValueKind == JsonValueKind.Number)
        room.MetersPerPixel = (float)mppElm.GetDouble();
    
    if (data.TryGetProperty("gridWidth", out JsonElement gwElm) && gwElm.ValueKind == JsonValueKind.Number)
        room.GridWidth = gwElm.GetDouble();
    
    if (data.TryGetProperty("gridHeight", out JsonElement ghElm) && ghElm.ValueKind == JsonValueKind.Number)
        room.GridHeight = ghElm.GetDouble();
    
    if (data.TryGetProperty("gridThicknessPx", out JsonElement gtpElm) && gtpElm.ValueKind == JsonValueKind.Number)
        room.GridThicknessPx = gtpElm.GetDouble();
    
    
    if (data.TryGetProperty("backgrounds", out JsonElement backgroundsElm) && backgroundsElm.ValueKind == JsonValueKind.Array)
    {
        room.Backgrounds.Clear();
        foreach (JsonElement bgElm in backgroundsElm.EnumerateArray())
        {
            var bg = new UndertaleRoom.Background();
            bg.ParentRoom = room;
            
            if (bgElm.TryGetProperty("enabled", out JsonElement enabledElm) && (enabledElm.ValueKind == JsonValueKind.True || enabledElm.ValueKind == JsonValueKind.False))
                bg.Enabled = enabledElm.GetBoolean();
            
            if (bgElm.TryGetProperty("foreground", out JsonElement foregroundElm) && (foregroundElm.ValueKind == JsonValueKind.True || foregroundElm.ValueKind == JsonValueKind.False))
                bg.Foreground = foregroundElm.GetBoolean();
            
            if (bgElm.TryGetProperty("backgroundDefinition", out JsonElement bgDefElm) && bgDefElm.ValueKind == JsonValueKind.String)
            {
                string bgName = bgDefElm.GetString();
                if (!string.IsNullOrEmpty(bgName))
                {
                    var bgDef = Data.Backgrounds.ByName(bgName);
                    if (bgDef != null)
                        bg.BackgroundDefinition = bgDef;
                }
            }
            
            if (bgElm.TryGetProperty("x", out JsonElement xElm) && xElm.ValueKind == JsonValueKind.Number)
                bg.X = xElm.GetInt32();
            
            if (bgElm.TryGetProperty("y", out JsonElement yElm) && yElm.ValueKind == JsonValueKind.Number)
                bg.Y = yElm.GetInt32();
            
            if (bgElm.TryGetProperty("tiledHorizontally", out JsonElement tiledHElm) && (tiledHElm.ValueKind == JsonValueKind.True || tiledHElm.ValueKind == JsonValueKind.False))
                bg.TiledHorizontally = tiledHElm.GetBoolean();
            
            if (bgElm.TryGetProperty("tiledVertically", out JsonElement tiledVElm) && (tiledVElm.ValueKind == JsonValueKind.True || tiledVElm.ValueKind == JsonValueKind.False))
                bg.TiledVertically = tiledVElm.GetBoolean();
            
            if (bgElm.TryGetProperty("speedX", out JsonElement speedXElm) && speedXElm.ValueKind == JsonValueKind.Number)
                bg.SpeedX = speedXElm.GetInt32();
            
            if (bgElm.TryGetProperty("speedY", out JsonElement speedYElm) && speedYElm.ValueKind == JsonValueKind.Number)
                bg.SpeedY = speedYElm.GetInt32();
            
            if (bgElm.TryGetProperty("stretch", out JsonElement stretchElm) && (stretchElm.ValueKind == JsonValueKind.True || stretchElm.ValueKind == JsonValueKind.False))
                bg.Stretch = stretchElm.GetBoolean();
            
            room.Backgrounds.Add(bg);
        }
    }
    
    
    if (data.TryGetProperty("views", out JsonElement viewsElm) && viewsElm.ValueKind == JsonValueKind.Array)
    {
        room.Views.Clear();
        foreach (JsonElement viewElm in viewsElm.EnumerateArray())
        {
            var view = new UndertaleRoom.View();
            
            if (viewElm.TryGetProperty("enabled", out JsonElement enabledElm) && (enabledElm.ValueKind == JsonValueKind.True || enabledElm.ValueKind == JsonValueKind.False))
                view.Enabled = enabledElm.GetBoolean();
            
            if (viewElm.TryGetProperty("viewX", out JsonElement vxElm) && vxElm.ValueKind == JsonValueKind.Number)
                view.ViewX = vxElm.GetInt32();
            
            if (viewElm.TryGetProperty("viewY", out JsonElement vyElm) && vyElm.ValueKind == JsonValueKind.Number)
                view.ViewY = vyElm.GetInt32();
            
            if (viewElm.TryGetProperty("viewWidth", out JsonElement vwElm) && vwElm.ValueKind == JsonValueKind.Number)
                view.ViewWidth = vwElm.GetInt32();
            
            if (viewElm.TryGetProperty("viewHeight", out JsonElement vhElm) && vhElm.ValueKind == JsonValueKind.Number)
                view.ViewHeight = vhElm.GetInt32();
            
            if (viewElm.TryGetProperty("portX", out JsonElement pxElm) && pxElm.ValueKind == JsonValueKind.Number)
                view.PortX = pxElm.GetInt32();
            
            if (viewElm.TryGetProperty("portY", out JsonElement pyElm) && pyElm.ValueKind == JsonValueKind.Number)
                view.PortY = pyElm.GetInt32();
            
            if (viewElm.TryGetProperty("portWidth", out JsonElement pwElm) && pwElm.ValueKind == JsonValueKind.Number)
                view.PortWidth = pwElm.GetInt32();
            
            if (viewElm.TryGetProperty("portHeight", out JsonElement phElm) && phElm.ValueKind == JsonValueKind.Number)
                view.PortHeight = phElm.GetInt32();
            
            if (viewElm.TryGetProperty("borderX", out JsonElement bxElm) && bxElm.ValueKind == JsonValueKind.Number)
                view.BorderX = (uint)Math.Max(0, bxElm.GetInt32());
            
            if (viewElm.TryGetProperty("borderY", out JsonElement byElm) && byElm.ValueKind == JsonValueKind.Number)
                view.BorderY = (uint)Math.Max(0, byElm.GetInt32());
            
            if (viewElm.TryGetProperty("speedX", out JsonElement sxElm) && sxElm.ValueKind == JsonValueKind.Number)
                view.SpeedX = sxElm.GetInt32();
            
            if (viewElm.TryGetProperty("speedY", out JsonElement syElm) && syElm.ValueKind == JsonValueKind.Number)
                view.SpeedY = syElm.GetInt32();
            
            if (viewElm.TryGetProperty("objectId", out JsonElement objIdElm) && objIdElm.ValueKind == JsonValueKind.String)
            {
                string objName = objIdElm.GetString();
                if (!string.IsNullOrEmpty(objName))
                {
                    var obj = Data.GameObjects.ByName(objName);
                    if (obj != null)
                        view.ObjectId = obj;
                }
            }
            
            room.Views.Add(view);
        }
    }
    
    
    if (data.TryGetProperty("gameObjects", out JsonElement gameObjectsElm) && gameObjectsElm.ValueKind == JsonValueKind.Array)
    {
        room.GameObjects.Clear();
        foreach (JsonElement objElm in gameObjectsElm.EnumerateArray())
        {
            var gameObj = new UndertaleRoom.GameObject();
            
            if (objElm.TryGetProperty("x", out JsonElement xElm) && xElm.ValueKind == JsonValueKind.Number)
                gameObj.X = xElm.GetInt32();
            
            if (objElm.TryGetProperty("y", out JsonElement yElm) && yElm.ValueKind == JsonValueKind.Number)
                gameObj.Y = yElm.GetInt32();
            
            if (objElm.TryGetProperty("objectDefinition", out JsonElement objDefElm) && objDefElm.ValueKind == JsonValueKind.String)
            {
                string objName = objDefElm.GetString();
                if (!string.IsNullOrEmpty(objName))
                {
                    var objDef = Data.GameObjects.ByName(objName);
                    if (objDef != null)
                        gameObj.ObjectDefinition = objDef;
                }
            }
            
            if (objElm.TryGetProperty("instanceID", out JsonElement instIdElm) && instIdElm.ValueKind == JsonValueKind.Number)
                gameObj.InstanceID = (uint)Math.Max(0, instIdElm.GetInt32());
            
            if (objElm.TryGetProperty("creationCode", out JsonElement codeElm) && codeElm.ValueKind == JsonValueKind.String)
            {
                string codeName = codeElm.GetString();
                if (!string.IsNullOrEmpty(codeName))
                {
                    var code = Data.Code.ByName(codeName);
                    if (code != null)
                        gameObj.CreationCode = code;
                }
            }
            
            if (objElm.TryGetProperty("scaleX", out JsonElement sxElm) && sxElm.ValueKind == JsonValueKind.Number)
                gameObj.ScaleX = (float)sxElm.GetDouble();
            
            if (objElm.TryGetProperty("scaleY", out JsonElement syElm) && syElm.ValueKind == JsonValueKind.Number)
                gameObj.ScaleY = (float)syElm.GetDouble();
            
            if (objElm.TryGetProperty("color", out JsonElement colorElm) && colorElm.ValueKind == JsonValueKind.Number)
                gameObj.Color = (uint)colorElm.GetInt32();
            
            if (objElm.TryGetProperty("rotation", out JsonElement rotElm) && rotElm.ValueKind == JsonValueKind.Number)
                gameObj.Rotation = (float)rotElm.GetDouble();
            
            if (objElm.TryGetProperty("preCreateCode", out JsonElement preCodeElm) && preCodeElm.ValueKind == JsonValueKind.String)
            {
                string preCodeName = preCodeElm.GetString();
                if (!string.IsNullOrEmpty(preCodeName))
                {
                    var preCode = Data.Code.ByName(preCodeName);
                    if (preCode != null)
                        gameObj.PreCreateCode = preCode;
                }
            }
            
            if (Data.IsVersionAtLeast(2, 2, 2, 302))
            {
                if (objElm.TryGetProperty("imageSpeed", out JsonElement imgSpeedElm) && imgSpeedElm.ValueKind == JsonValueKind.Number)
                    gameObj.ImageSpeed = (float)imgSpeedElm.GetDouble();
                
                if (objElm.TryGetProperty("imageIndex", out JsonElement imgIndexElm) && imgIndexElm.ValueKind == JsonValueKind.Number)
                    gameObj.ImageIndex = imgIndexElm.GetInt32();
            }
            
            room.GameObjects.Add(gameObj);
        }
    }
    
    
    if (data.TryGetProperty("tiles", out JsonElement tilesElm) && tilesElm.ValueKind == JsonValueKind.Array)
    {
        room.Tiles.Clear();
        foreach (JsonElement tileElm in tilesElm.EnumerateArray())
        {
            var tile = new UndertaleRoom.Tile();
            
            if (tileElm.TryGetProperty("x", out JsonElement xElm) && xElm.ValueKind == JsonValueKind.Number)
                tile.X = xElm.GetInt32();
            
            if (tileElm.TryGetProperty("y", out JsonElement yElm) && yElm.ValueKind == JsonValueKind.Number)
                tile.Y = yElm.GetInt32();
            
            if (tileElm.TryGetProperty("spriteMode", out JsonElement spriteModeElm) && (spriteModeElm.ValueKind == JsonValueKind.True || spriteModeElm.ValueKind == JsonValueKind.False))
                tile.spriteMode = spriteModeElm.GetBoolean();
            
            if (tile.spriteMode)
            {
                if (tileElm.TryGetProperty("spriteDefinition", out JsonElement spriteDefElm) && spriteDefElm.ValueKind == JsonValueKind.String)
                {
                    string spriteName = spriteDefElm.GetString();
                    if (!string.IsNullOrEmpty(spriteName))
                    {
                        var sprite = Data.Sprites.ByName(spriteName);
                        if (sprite != null)
                            tile.SpriteDefinition = sprite;
                    }
                }
            }
            else
            {
                if (tileElm.TryGetProperty("backgroundDefinition", out JsonElement bgDefElm) && bgDefElm.ValueKind == JsonValueKind.String)
                {
                    string bgName = bgDefElm.GetString();
                    if (!string.IsNullOrEmpty(bgName))
                    {
                        var bg = Data.Backgrounds.ByName(bgName);
                        if (bg != null)
                            tile.BackgroundDefinition = bg;
                    }
                }
            }
            
            if (tileElm.TryGetProperty("sourceX", out JsonElement sxElm) && sxElm.ValueKind == JsonValueKind.Number)
                tile.SourceX = sxElm.GetInt32();
            
            if (tileElm.TryGetProperty("sourceY", out JsonElement syElm) && syElm.ValueKind == JsonValueKind.Number)
                tile.SourceY = syElm.GetInt32();
            
            if (tileElm.TryGetProperty("width", out JsonElement wElm) && wElm.ValueKind == JsonValueKind.Number)
                tile.Width = (uint)Math.Max(0, wElm.GetInt32());
            
            if (tileElm.TryGetProperty("height", out JsonElement hElm) && hElm.ValueKind == JsonValueKind.Number)
                tile.Height = (uint)Math.Max(0, hElm.GetInt32());
            
            if (tileElm.TryGetProperty("tileDepth", out JsonElement depthElm) && depthElm.ValueKind == JsonValueKind.Number)
                tile.TileDepth = depthElm.GetInt32();
            
            if (tileElm.TryGetProperty("instanceID", out JsonElement instIdElm) && instIdElm.ValueKind == JsonValueKind.Number)
                tile.InstanceID = (uint)Math.Max(0, instIdElm.GetInt32());
            
            if (tileElm.TryGetProperty("scaleX", out JsonElement scxElm) && scxElm.ValueKind == JsonValueKind.Number)
                tile.ScaleX = (float)scxElm.GetDouble();
            
            if (tileElm.TryGetProperty("scaleY", out JsonElement scyElm) && scyElm.ValueKind == JsonValueKind.Number)
                tile.ScaleY = (float)scyElm.GetDouble();
            
            if (tileElm.TryGetProperty("color", out JsonElement colorElm) && colorElm.ValueKind == JsonValueKind.Number)
                tile.Color = (uint)colorElm.GetInt32();
            
            room.Tiles.Add(tile);
        }
    }
    
    
    if (Data.IsGameMaker2() && data.TryGetProperty("layers", out JsonElement layersElm) && layersElm.ValueKind == JsonValueKind.Array)
    {
        
        
        PrintLine("[ImportRooms] Layer import is not fully implemented - preserving existing layers.");
    }
    
    
    if (Data.IsVersionAtLeast(2, 3) && data.TryGetProperty("sequences", out JsonElement sequencesElm) && sequencesElm.ValueKind == JsonValueKind.Array)
    {
        room.Sequences.Clear();
        foreach (JsonElement seqElm in sequencesElm.EnumerateArray())
        {
            if (seqElm.ValueKind == JsonValueKind.String)
            {
                string seqName = seqElm.GetString();
                if (!string.IsNullOrEmpty(seqName))
                {
                    var seq = Data.Sequences.ByName(seqName);
                    if (seq != null)
                    {
                        var seqRef = new UndertaleResourceById<UndertaleSequence, UndertaleChunkSEQN>();
                        seqRef.Resource = seq;
                        room.Sequences.Add(seqRef);
                    }
                }
            }
        }
    }
    
    
    if (Data.IsVersionAtLeast(2024, 13) && data.TryGetProperty("instanceCreationOrderIDs", out JsonElement orderIdsElm) && orderIdsElm.ValueKind == JsonValueKind.Array)
    {
        if (room.InstanceCreationOrderIDs == null)
            room.InstanceCreationOrderIDs = new UndertaleRoom.InstanceIDList();
        
        room.InstanceCreationOrderIDs.InstanceIDs.Clear();
        foreach (JsonElement idElm in orderIdsElm.EnumerateArray())
        {
            if (idElm.ValueKind == JsonValueKind.Number)
                room.InstanceCreationOrderIDs.InstanceIDs.Add(idElm.GetInt32());
        }
    }
}

