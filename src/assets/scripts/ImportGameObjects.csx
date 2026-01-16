#load "SharedPaths.csx"

using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.Text.Json;
using UndertaleModLib;
using UndertaleModLib.Models;

EnsureDataLoaded();

ImportContext ctx = PrepareImportContext();
string gameObjectsIn = Path.Combine(ctx.ObjectsFolder, "GameObjects");

if (!Directory.Exists(gameObjectsIn))
{
    ScriptMessage($"[ImportGameObjects] No GameObjects folder found at {gameObjectsIn}");
    return;
}

int gameObjectsImported = 0;
int gameObjectsCreated = 0;

var jsonFiles = Directory.GetFiles(gameObjectsIn, "*.json");
ScriptMessage($"[ImportGameObjects] Found {jsonFiles.Length} game object files to import");

foreach (string jsonFile in jsonFiles)
{
    try
    {
        string jsonContent = File.ReadAllText(jsonFile);
        JsonDocument jsonDoc = JsonDocument.Parse(jsonContent);
        JsonElement root = jsonDoc.RootElement;

        string objName = "";
        if (root.TryGetProperty("name", out JsonElement nameElm))
        {
            objName = nameElm.GetString();
        }
        else
        {
            objName = Path.GetFileNameWithoutExtension(jsonFile);
        }

        if (string.IsNullOrEmpty(objName)) continue;

        UndertaleGameObject gameObject = Data.GameObjects.ByName(objName);
        bool isNew = false;
        
        if (gameObject == null)
        {
            gameObject = new UndertaleGameObject();
            gameObject.Name = Data.Strings.MakeString(objName);
            isNew = true;
            gameObjectsCreated++;
        }

        if (root.TryGetProperty("sprite", out JsonElement spriteElm))
        {
            string spriteName = spriteElm.GetString();
            if (!string.IsNullOrEmpty(spriteName))
            {
                gameObject.Sprite = Data.Sprites.ByName(spriteName);
            }
            else
            {
                gameObject.Sprite = null;
            }
        }

        if (root.TryGetProperty("visible", out JsonElement visibleElm))
            gameObject.Visible = visibleElm.GetBoolean();
        if (root.TryGetProperty("solid", out JsonElement solidElm))
            gameObject.Solid = solidElm.GetBoolean();
        if (root.TryGetProperty("depth", out JsonElement depthElm))
            gameObject.Depth = depthElm.GetInt32();
        if (root.TryGetProperty("persistent", out JsonElement persistentElm))
            gameObject.Persistent = persistentElm.GetBoolean();

        if (root.TryGetProperty("parent", out JsonElement parentElm))
        {
            string parentName = parentElm.GetString();
            if (!string.IsNullOrEmpty(parentName))
            {
                gameObject.ParentId = Data.GameObjects.ByName(parentName);
            }
            else
            {
                gameObject.ParentId = null;
            }
        }

        if (root.TryGetProperty("textureMask", out JsonElement textureMaskElm))
        {
            string textureMaskName = textureMaskElm.GetString();
            if (!string.IsNullOrEmpty(textureMaskName))
            {
                gameObject.TextureMaskId = Data.Sprites.ByName(textureMaskName);
            }
            else
            {
                gameObject.TextureMaskId = null;
            }
        }

        if (Data.IsVersionAtLeast(2022, 5) && root.TryGetProperty("managed", out JsonElement managedElm))
        {
            gameObject.Managed = managedElm.GetBoolean();
        }

        if (root.TryGetProperty("usesPhysics", out JsonElement usesPhysicsElm))
        {
            gameObject.UsesPhysics = usesPhysicsElm.GetBoolean();

            if (gameObject.UsesPhysics)
            {
                if (root.TryGetProperty("isSensor", out JsonElement isSensorElm))
                    gameObject.IsSensor = isSensorElm.GetBoolean();
                if (root.TryGetProperty("collisionShape", out JsonElement collisionShapeElm))
                    gameObject.CollisionShape = (CollisionShapeFlags)collisionShapeElm.GetInt32();
                if (root.TryGetProperty("density", out JsonElement densityElm))
                    gameObject.Density = (float)densityElm.GetDouble();
                if (root.TryGetProperty("restitution", out JsonElement restitutionElm))
                    gameObject.Restitution = (float)restitutionElm.GetDouble();
                if (root.TryGetProperty("group", out JsonElement groupElm))
                    gameObject.Group = (uint)groupElm.GetInt64();
                if (root.TryGetProperty("linearDamping", out JsonElement linearDampingElm))
                    gameObject.LinearDamping = (float)linearDampingElm.GetDouble();
                if (root.TryGetProperty("angularDamping", out JsonElement angularDampingElm))
                    gameObject.AngularDamping = (float)angularDampingElm.GetDouble();
                if (root.TryGetProperty("friction", out JsonElement frictionElm))
                    gameObject.Friction = (float)frictionElm.GetDouble();
                if (root.TryGetProperty("awake", out JsonElement awakeElm))
                    gameObject.Awake = awakeElm.GetBoolean();
                if (root.TryGetProperty("kinematic", out JsonElement kinematicElm))
                    gameObject.Kinematic = kinematicElm.GetBoolean();

                if (root.TryGetProperty("physicsVertices", out JsonElement verticesElm) && verticesElm.ValueKind == JsonValueKind.Array)
                {
                    gameObject.PhysicsVertices.Clear();
                    foreach (var vertexElm in verticesElm.EnumerateArray())
                    {
                        var vertex = new UndertalePhysicsVertex();
                        if (vertexElm.TryGetProperty("x", out JsonElement xElm))
                            vertex.X = (float)xElm.GetDouble();
                        if (vertexElm.TryGetProperty("y", out JsonElement yElm))
                            vertex.Y = (float)yElm.GetDouble();
                        gameObject.PhysicsVertices.Add(vertex);
                    }
                }
            }
        }

        if (root.TryGetProperty("events", out JsonElement eventsElm) && eventsElm.ValueKind == JsonValueKind.Array)
        {
            foreach (var eventElm in eventsElm.EnumerateArray())
            {
                if (!eventElm.TryGetProperty("eventType", out JsonElement eventTypeElm)) continue;
                if (!eventElm.TryGetProperty("eventSubtype", out JsonElement eventSubtypeElm)) continue;

                int eventType = eventTypeElm.GetInt32();
                uint eventSubtype = (uint)eventSubtypeElm.GetInt64();

                if (eventType < 0 || eventType >= gameObject.Events.Count) continue;

                UndertaleGameObject.Event existingEvent = null;
                foreach (var evt in gameObject.Events[eventType])
                {
                    if (evt.EventSubtype == eventSubtype)
                    {
                        existingEvent = evt;
                        break;
                    }
                }

                if (existingEvent == null)
                {
                    existingEvent = new UndertaleGameObject.Event();
                    existingEvent.EventSubtype = eventSubtype;
                    gameObject.Events[eventType].Add(existingEvent);
                }

                if (eventElm.TryGetProperty("actions", out JsonElement actionsElm) && actionsElm.ValueKind == JsonValueKind.Array)
                {
                    int actionIndex = 0;
                    foreach (var actionElm in actionsElm.EnumerateArray())
                    {
                        UndertaleGameObject.EventAction action;
                        if (actionIndex < existingEvent.Actions.Count)
                        {
                            action = existingEvent.Actions[actionIndex];
                        }
                        else
                        {
                            action = new UndertaleGameObject.EventAction();
                            existingEvent.Actions.Add(action);
                        }

                        if (actionElm.TryGetProperty("libId", out JsonElement libIdElm))
                            action.LibID = (uint)libIdElm.GetInt64();
                        if (actionElm.TryGetProperty("id", out JsonElement idElm))
                            action.ID = (uint)idElm.GetInt64();
                        if (actionElm.TryGetProperty("kind", out JsonElement kindElm))
                            action.Kind = (uint)kindElm.GetInt64();
                        if (actionElm.TryGetProperty("useRelative", out JsonElement useRelativeElm))
                            action.UseRelative = useRelativeElm.GetBoolean();
                        if (actionElm.TryGetProperty("isQuestion", out JsonElement isQuestionElm))
                            action.IsQuestion = isQuestionElm.GetBoolean();
                        if (actionElm.TryGetProperty("useApplyTo", out JsonElement useApplyToElm))
                            action.UseApplyTo = useApplyToElm.GetBoolean();
                        if (actionElm.TryGetProperty("exeType", out JsonElement exeTypeElm))
                            action.ExeType = (uint)exeTypeElm.GetInt64();
                        if (actionElm.TryGetProperty("actionName", out JsonElement actionNameElm))
                        {
                            string actionName = actionNameElm.GetString();
                            if (!string.IsNullOrEmpty(actionName))
                                action.ActionName = Data.Strings.MakeString(actionName);
                        }
                        if (actionElm.TryGetProperty("codeId", out JsonElement codeIdElm))
                        {
                            string codeIdName = codeIdElm.GetString();
                            if (!string.IsNullOrEmpty(codeIdName))
                                action.CodeId = Data.Code.ByName(codeIdName);
                        }
                        if (actionElm.TryGetProperty("argumentCount", out JsonElement argumentCountElm))
                            action.ArgumentCount = (uint)argumentCountElm.GetInt64();
                        if (actionElm.TryGetProperty("who", out JsonElement whoElm))
                            action.Who = whoElm.GetInt32();
                        if (actionElm.TryGetProperty("relative", out JsonElement relativeElm))
                            action.Relative = relativeElm.GetBoolean();
                        if (actionElm.TryGetProperty("isNot", out JsonElement isNotElm))
                            action.IsNot = isNotElm.GetBoolean();

                        actionIndex++;
                    }
                }
            }
        }

        if (isNew)
        {
            Data.GameObjects.Add(gameObject);
        }

        gameObjectsImported++;
    }
    catch (Exception ex)
    {
        ScriptMessage($"[ImportGameObjects] Error importing {Path.GetFileName(jsonFile)}: {ex.Message}");
    }
}

ScriptMessage($"[ImportGameObjects] Imported {gameObjectsImported} game objects ({gameObjectsCreated} new)");
