


using System;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Linq;
using System.Threading.Tasks;
using System.Collections.Generic;
using UndertaleModLib;
using UndertaleModLib.Models;




string OutputDirectory = "";




void PrintLine(string s) => Console.WriteLine(s);

string SafeName(string name)
{
    var invalid = Path.GetInvalidFileNameChars();
    var sb = new StringBuilder(name.Length);
    foreach (var ch in name) sb.Append(invalid.Contains(ch) ? '_' : ch);
    return sb.ToString();
}

string ResolveOutputDirectory()
{
    if (!string.IsNullOrEmpty(OutputDirectory) && Directory.Exists(OutputDirectory))
        return OutputDirectory;

    if (string.IsNullOrEmpty(FilePath))
        throw new ScriptException("No data.win file loaded. Please load a game data file first.");

    string dataWinDir = Path.GetDirectoryName(FilePath);
    string outputDir = Path.Combine(dataWinDir, "Objects", "Rooms");
    Directory.CreateDirectory(outputDir);
    return outputDir;
}




EnsureDataLoaded();

string roomsOut = ResolveOutputDirectory();
PrintLine($"[ExportRooms] Exporting to: {roomsOut}");

List<UndertaleRoom> allRooms = Data.Rooms.ToList();
PrintLine($"[ExportRooms] Found {allRooms.Count} rooms to export.");

SetProgressBar(null, "Exporting Rooms", 0, allRooms.Count);
StartProgressBarUpdater();

await Task.Run(() => Parallel.ForEach(allRooms, room => ExportRoom(room, roomsOut)));

void ExportRoom(UndertaleRoom room, string outputDir)
{
    if (room?.Name?.Content == null)
    {
        IncrementProgressParallel();
        return;
    }

    try
    {
        string name = SafeName(room.Name.Content);
        string jsonPath = Path.Combine(outputDir, name + ".json");

        using (var stream = new FileStream(jsonPath, FileMode.Create, FileAccess.Write))
        using (var writer = new Utf8JsonWriter(stream, new JsonWriterOptions { Indented = true }))
        {
            writer.WriteStartObject();

            writer.WriteString("name", room.Name.Content);
            writer.WriteString("caption", room.Caption?.Content ?? "");
            writer.WriteNumber("width", (int)room.Width);
            writer.WriteNumber("height", (int)room.Height);
            writer.WriteNumber("speed", (int)room.Speed);
            writer.WriteBoolean("persistent", room.Persistent);
            writer.WriteNumber("backgroundColor", (int)room.BackgroundColor);
            writer.WriteBoolean("drawBackgroundColor", room.DrawBackgroundColor);
            writer.WriteString("creationCodeId", room.CreationCodeId?.Name?.Content ?? "");
            writer.WriteNumber("flags", (int)room.Flags);
            writer.WriteBoolean("world", room.World);
            writer.WriteNumber("top", (int)room.Top);
            writer.WriteNumber("left", (int)room.Left);
            writer.WriteNumber("right", (int)room.Right);
            writer.WriteNumber("bottom", (int)room.Bottom);
            writer.WriteNumber("gravityX", room.GravityX);
            writer.WriteNumber("gravityY", room.GravityY);
            writer.WriteNumber("metersPerPixel", room.MetersPerPixel);
            writer.WriteNumber("gridWidth", (float)room.GridWidth);
            writer.WriteNumber("gridHeight", (float)room.GridHeight);
            writer.WriteNumber("gridThicknessPx", (float)room.GridThicknessPx);

            
            writer.WriteStartArray("backgrounds");
            foreach (var bg in room.Backgrounds)
            {
                writer.WriteStartObject();
                writer.WriteBoolean("enabled", bg.Enabled);
                writer.WriteBoolean("foreground", bg.Foreground);
                writer.WriteString("backgroundDefinition", bg.BackgroundDefinition?.Name?.Content ?? "");
                writer.WriteNumber("x", bg.X);
                writer.WriteNumber("y", bg.Y);
                writer.WriteBoolean("tiledHorizontally", bg.TiledHorizontally);
                writer.WriteBoolean("tiledVertically", bg.TiledVertically);
                writer.WriteNumber("speedX", bg.SpeedX);
                writer.WriteNumber("speedY", bg.SpeedY);
                writer.WriteBoolean("stretch", bg.Stretch);
                writer.WriteEndObject();
            }
            writer.WriteEndArray();

            
            writer.WriteStartArray("views");
            foreach (var view in room.Views)
            {
                writer.WriteStartObject();
                writer.WriteBoolean("enabled", view.Enabled);
                writer.WriteNumber("viewX", view.ViewX);
                writer.WriteNumber("viewY", view.ViewY);
                writer.WriteNumber("viewWidth", view.ViewWidth);
                writer.WriteNumber("viewHeight", view.ViewHeight);
                writer.WriteNumber("portX", view.PortX);
                writer.WriteNumber("portY", view.PortY);
                writer.WriteNumber("portWidth", view.PortWidth);
                writer.WriteNumber("portHeight", view.PortHeight);
                writer.WriteNumber("borderX", (int)view.BorderX);
                writer.WriteNumber("borderY", (int)view.BorderY);
                writer.WriteNumber("speedX", view.SpeedX);
                writer.WriteNumber("speedY", view.SpeedY);
                writer.WriteString("objectId", view.ObjectId?.Name?.Content ?? "");
                writer.WriteEndObject();
            }
            writer.WriteEndArray();

            
            writer.WriteStartArray("gameObjects");
            foreach (var obj in room.GameObjects)
            {
                writer.WriteStartObject();
                writer.WriteNumber("x", obj.X);
                writer.WriteNumber("y", obj.Y);
                writer.WriteString("objectDefinition", obj.ObjectDefinition?.Name?.Content ?? "");
                writer.WriteNumber("instanceID", (int)obj.InstanceID);
                writer.WriteString("creationCode", obj.CreationCode?.Name?.Content ?? "");
                writer.WriteNumber("scaleX", obj.ScaleX);
                writer.WriteNumber("scaleY", obj.ScaleY);
                writer.WriteNumber("color", (int)obj.Color);
                writer.WriteNumber("rotation", obj.Rotation);
                writer.WriteString("preCreateCode", obj.PreCreateCode?.Name?.Content ?? "");
                if (Data.IsVersionAtLeast(2, 2, 2, 302))
                {
                    writer.WriteNumber("imageSpeed", obj.ImageSpeed);
                    writer.WriteNumber("imageIndex", obj.ImageIndex);
                }
                writer.WriteEndObject();
            }
            writer.WriteEndArray();

            
            writer.WriteStartArray("tiles");
            foreach (var tile in room.Tiles)
            {
                writer.WriteStartObject();
                writer.WriteNumber("x", tile.X);
                writer.WriteNumber("y", tile.Y);
                writer.WriteBoolean("spriteMode", tile.spriteMode);
                if (tile.spriteMode)
                    writer.WriteString("spriteDefinition", tile.SpriteDefinition?.Name?.Content ?? "");
                else
                    writer.WriteString("backgroundDefinition", tile.BackgroundDefinition?.Name?.Content ?? "");
                writer.WriteNumber("sourceX", tile.SourceX);
                writer.WriteNumber("sourceY", tile.SourceY);
                writer.WriteNumber("width", (int)tile.Width);
                writer.WriteNumber("height", (int)tile.Height);
                writer.WriteNumber("tileDepth", tile.TileDepth);
                writer.WriteNumber("instanceID", (int)tile.InstanceID);
                writer.WriteNumber("scaleX", tile.ScaleX);
                writer.WriteNumber("scaleY", tile.ScaleY);
                writer.WriteNumber("color", (int)tile.Color);
                writer.WriteEndObject();
            }
            writer.WriteEndArray();

            
            if (Data.IsGameMaker2() && room.Layers != null && room.Layers.Count > 0)
            {
                writer.WriteStartArray("layers");
                foreach (var layer in room.Layers)
                {
                    writer.WriteStartObject();
                    writer.WriteString("layerName", layer.LayerName?.Content ?? "");
                    writer.WriteNumber("layerId", (int)layer.LayerId);
                    writer.WriteNumber("layerType", (int)layer.LayerType);
                    writer.WriteNumber("layerDepth", layer.LayerDepth);
                    writer.WriteNumber("xOffset", layer.XOffset);
                    writer.WriteNumber("yOffset", layer.YOffset);
                    writer.WriteNumber("hSpeed", layer.HSpeed);
                    writer.WriteNumber("vSpeed", layer.VSpeed);
                    writer.WriteBoolean("isVisible", layer.IsVisible);
                    
                    if (Data.IsVersionAtLeast(2022, 1))
                    {
                        writer.WriteBoolean("effectEnabled", layer.EffectEnabled);
                        writer.WriteString("effectType", layer.EffectType?.Content ?? "");
                    }

                    if (layer.LayerType == UndertaleRoom.LayerType.Instances && layer.InstancesData != null)
                    {
                        writer.WriteStartArray("instanceIds");
                        if (layer.InstancesData.Instances != null)
                        {
                            foreach (var inst in layer.InstancesData.Instances)
                                writer.WriteNumberValue((int)inst.InstanceID);
                        }
                        writer.WriteEndArray();
                    }
                    else if (layer.LayerType == UndertaleRoom.LayerType.Tiles && layer.TilesData != null)
                    {
                        var tilesData = layer.TilesData;
                        writer.WriteString("tilesBackground", tilesData.Background?.Name?.Content ?? "");
                        writer.WriteNumber("tilesX", (int)tilesData.TilesX);
                        writer.WriteNumber("tilesY", (int)tilesData.TilesY);
                        writer.WriteStartArray("tileData");
                        if (tilesData.TileData != null)
                        {
                            foreach (var row in tilesData.TileData)
                            {
                                writer.WriteStartArray();
                                if (row != null)
                                    foreach (var value in row)
                                        writer.WriteNumberValue(value);
                                writer.WriteEndArray();
                            }
                        }
                        writer.WriteEndArray();
                    }
                    else if (layer.LayerType == UndertaleRoom.LayerType.Background && layer.BackgroundData != null)
                    {
                        var bgData = layer.BackgroundData;
                        writer.WriteStartObject("backgroundData");
                        writer.WriteBoolean("visible", bgData.Visible);
                        writer.WriteBoolean("foreground", bgData.Foreground);
                        writer.WriteString("sprite", bgData.Sprite?.Name?.Content ?? "");
                        writer.WriteBoolean("tiledHorizontally", bgData.TiledHorizontally);
                        writer.WriteBoolean("tiledVertically", bgData.TiledVertically);
                        writer.WriteBoolean("stretch", bgData.Stretch);
                        writer.WriteNumber("color", (int)bgData.Color);
                        writer.WriteNumber("firstFrame", bgData.FirstFrame);
                        writer.WriteNumber("animationSpeed", bgData.AnimationSpeed);
                        writer.WriteNumber("animationSpeedType", (int)bgData.AnimationSpeedType);
                        writer.WriteEndObject();
                    }
                    else if (layer.LayerType == UndertaleRoom.LayerType.Assets && layer.AssetsData != null)
                    {
                        var assetsData = layer.AssetsData;
                        writer.WriteStartObject("assetsData");

                        writer.WriteStartArray("legacyTiles");
                        if (assetsData.LegacyTiles != null)
                        {
                            foreach (var tile in assetsData.LegacyTiles)
                            {
                                writer.WriteStartObject();
                                writer.WriteNumber("x", tile.X);
                                writer.WriteNumber("y", tile.Y);
                                writer.WriteNumber("sourceX", (int)tile.SourceX);
                                writer.WriteNumber("sourceY", (int)tile.SourceY);
                                writer.WriteNumber("width", (int)tile.Width);
                                writer.WriteNumber("height", (int)tile.Height);
                                writer.WriteNumber("tileDepth", tile.TileDepth);
                                writer.WriteNumber("instanceID", (int)tile.InstanceID);
                                writer.WriteNumber("scaleX", tile.ScaleX);
                                writer.WriteNumber("scaleY", tile.ScaleY);
                                writer.WriteNumber("color", (int)tile.Color);
                                writer.WriteString("background", tile.BackgroundDefinition?.Name?.Content ?? "");
                                writer.WriteEndObject();
                            }
                        }
                        writer.WriteEndArray();

                        writer.WriteStartArray("sprites");
                        if (assetsData.Sprites != null)
                        {
                            foreach (var spr in assetsData.Sprites)
                            {
                                writer.WriteStartObject();
                                writer.WriteString("name", spr.Name?.Content ?? "");
                                writer.WriteString("sprite", spr.Sprite?.Name?.Content ?? "");
                                writer.WriteNumber("x", spr.X);
                                writer.WriteNumber("y", spr.Y);
                                writer.WriteNumber("scaleX", spr.ScaleX);
                                writer.WriteNumber("scaleY", spr.ScaleY);
                                writer.WriteNumber("color", (int)spr.Color);
                                writer.WriteNumber("animationSpeed", spr.AnimationSpeed);
                                writer.WriteNumber("animationSpeedType", (int)spr.AnimationSpeedType);
                                writer.WriteNumber("frameIndex", spr.FrameIndex);
                                writer.WriteNumber("rotation", spr.Rotation);
                                writer.WriteEndObject();
                            }
                        }
                        writer.WriteEndArray();

                        writer.WriteEndObject();
                    }

                    writer.WriteEndObject();
                }
                writer.WriteEndArray();
            }

            
            if (Data.IsVersionAtLeast(2, 3) && room.Sequences != null && room.Sequences.Count > 0)
            {
                writer.WriteStartArray("sequences");
                foreach (var seq in room.Sequences)
                    writer.WriteStringValue(seq?.Resource?.Name?.Content ?? "");
                writer.WriteEndArray();
            }

            
            if (Data.IsVersionAtLeast(2024, 13) && room.InstanceCreationOrderIDs?.InstanceIDs != null && room.InstanceCreationOrderIDs.InstanceIDs.Count > 0)
            {
                writer.WriteStartArray("instanceCreationOrderIDs");
                foreach (var id in room.InstanceCreationOrderIDs.InstanceIDs)
                    writer.WriteNumberValue(id);
                writer.WriteEndArray();
            }

            writer.WriteEndObject();
        }
    }
    catch (Exception ex)
    {
        PrintLine($"[ExportRooms] Failed to export room {room.Name?.Content}: {ex.Message}");
    }

    IncrementProgressParallel();
}

await StopProgressBarUpdater();
HideProgressBar();

PrintLine($"[ExportRooms] Export complete. {allRooms.Count} rooms exported to {roomsOut}");
