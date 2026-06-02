using System.Text.Json.Serialization;

namespace CropSentinel.AgentNativeService;

[JsonSerializable(typeof(PayloadManifest))]
internal sealed partial class WatchdogJsonSerializerContext : JsonSerializerContext
{
}
