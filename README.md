# gltf-tools

### Saving separate textures https://www.npmjs.com/package/gltf-pipeline#saving-separate-textures-1
```python
from pygltflib import GLTF2,BufferFormat
from pygltflib.utils import ImageFormat
filename = "C.glb"
gltf = GLTF2().load(filename)
# gltf.images[0].name = gltf.images[0].uri  # will save the data uri to this file (regardless of data format)
gltf.convert_images(ImageFormat.FILE, path='img',override=True)
for item in gltf.images:
    bufferView =  item.bufferView
    gltf.remove_bufferView(bufferView)
for item in gltf.images:
    del item.bufferView
gltf.convert_buffers(BufferFormat.BINARYBLOB,override=True)
gltf.save("img/c.glb")
```
