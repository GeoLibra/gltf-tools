import io
import time
import shutil
import os
import mimetypes
from os import path
from gltflib import GLTF, Image as GLTF_Image, Buffer, FileResource, padbytes, GLBResource, Base64Resource
from PIL import Image
from datetime import timedelta


SAMPLE_DIR = "./"
OUT_DIR = "./"


def optimize_gltf(filename, output_filename):
    task_start = time.time()
    gltf = GLTF.load(filename)
    num_images = len(gltf.model.images)
    print(f"Optimizing {num_images} image(s) in GLTF file: \"{filename}\"")
    for i, image in enumerate(gltf.model.images):
        print(f"  Optimizing image {i+1} of {num_images} (URI: {image.uri or None})")
        compressed_image_data = optimize_gltf_image(gltf, image)
        replace_image(gltf, image, compressed_image_data)
    print(f"  Generating output file: \"{output_filename}\"")
    compressed_gltf = gltf.export(output_filename)
    print(f"  Finished optimizing \"{filename}\" to \"{output_filename}\"")
    orig_size = get_gltf_size(filename, gltf)
    new_size = get_gltf_size(output_filename, compressed_gltf)
    reduction = 100 * (orig_size - new_size) / orig_size
    print(f"    Original size (including external file resources): {format_size(orig_size)}")
    print(f"    New size (including external file resources): {format_size(new_size)}")
    print(f"    Reduction: {reduction:.1f}%")
    task_end = time.time()
    elapsed = task_end - task_start
    print(f"  Elapsed: {str(timedelta(seconds=elapsed))}")


def optimize_gltf_image(gltf: GLTF, image: GLTF_Image) -> bytes:
    task_start = time.time()
    im, orig_size = gltf_image_to_pillow(gltf, image)
    image_format = get_image_format(image)
    print(f"    Original size: {format_size(orig_size)}")
    # im.show()
    fp = io.BytesIO()
    im.save(fp, format=image_format, optimize=True, quality=95)
    compressed_size = fp.getbuffer().nbytes
    print(f"    Compressed size: {format_size(compressed_size)}")
    delta = orig_size - compressed_size
    reduction = 100 * delta / orig_size
    print(f"    Reduction: {reduction:.1f}%")
    task_end = time.time()
    elapsed = task_end - task_start
    print(f"    Elapsed: {str(timedelta(seconds=elapsed))}")
    fp.seek(0)
    return fp.read()


def get_image_format(image: GLTF_Image) -> str:
    mime_type = image.mimeType
    if mime_type is None:
        if image.uri is None:
            raise RuntimeError(f"Image is missing MIME type and has no URI - unable to determine image type")
        mime_type = mimetypes.guess_type(image.uri)[0]
    if mime_type == 'image/png':
        return 'png'
    elif mime_type == 'image/jpeg':
        return 'jpeg'
    else:
        raise RuntimeError(f"Unsupported image MIME type: {mime_type}")


def replace_image(gltf: GLTF, image: GLTF_Image, compressed_image_data: bytes):
    if image.uri is None:
        # Image data is in a buffer (typically an embedded GLB buffer, though it may be a buffer with an external URI).
        # Get the buffer data.
        buffer_view = gltf.model.bufferViews[image.bufferView]
        buffer = gltf.model.buffers[buffer_view.buffer]
        start = buffer_view.byteOffset or 0
        orig_bytelen = buffer_view.byteLength
        orig_end = start + orig_bytelen
        data = bytearray(get_buffer_data(gltf, buffer))

        # Ensure compressed image data aligns to a 4-byte boundary
        padded_compressed_image_data = bytearray(compressed_image_data)
        bytelen = padbytes(padded_compressed_image_data, 4)

        # Replace the original image data with the compressed data.
        data[start:orig_end] = padded_compressed_image_data
        replace_buffer_data(gltf, buffer, data)

        # Get the new length and update it on the buffer view
        buffer_view.byteLength = bytelen

        # Update byte offsets on all subsequent buffer views
        delta = bytelen - orig_bytelen
        for buffer_view in gltf.model.bufferViews[(image.bufferView + 1):]:
            buffer_view.byteOffset += delta

        # Update total byte length on buffer
        buffer.byteLength += delta
    else:
        # Image is an external file. Replace the corresponding FileResource with a new FileResource containing the
        # compressed image data.
        resource = gltf.get_resource(image.uri)
        i = gltf.resources.index(resource)
        new_file_resource = FileResource(image.uri, data=compressed_image_data, mimetype=image.mimeType)
        gltf.resources[i] = new_file_resource


def gltf_image_to_pillow(gltf: GLTF, image: GLTF_Image) -> (Image, int):
    data = get_gltf_image_data(gltf, image)
    return Image.open(io.BytesIO(data)), len(data)


def get_gltf_image_data(gltf: GLTF, image: GLTF_Image) -> bytes:
    if image.uri is None:
        buffer_view = gltf.model.bufferViews[image.bufferView]
        buffer = gltf.model.buffers[buffer_view.buffer]
        data = get_buffer_data(gltf, buffer)
        start = buffer_view.byteOffset or 0
        end = start + buffer_view.byteLength
        return data[start:end]
    else:
        resource = gltf.get_resource(image.uri)
        if isinstance(resource, FileResource):
            resource.load()
        return resource.data


def get_buffer_data(gltf: GLTF, buffer: Buffer) -> bytes:
    resource = gltf.get_glb_resource() if buffer.uri is None else gltf.get_resource(buffer.uri)
    if isinstance(resource, FileResource):
        resource.load()
    return resource.data


def replace_buffer_data(gltf: GLTF, buffer: Buffer, data: bytes):
    if buffer.uri is None:
        resource = gltf.get_glb_resource()
        i = gltf.resources.index(resource)
        new_glb_resource = GLBResource(data)
        gltf.resources[i] = new_glb_resource
    else:
        resource = gltf.get_resource(buffer.uri)
        i = gltf.resources.index(resource)
        if isinstance(resource, FileResource):
            new_file_resource = FileResource(resource.filename, data=data, mimetype=resource.mimetype)
            gltf.resources[i] = new_file_resource
        elif isinstance(resource, Base64Resource):
            new_b64_resource = Base64Resource(data, resource.mime_type)
            gltf.resources[i] = new_b64_resource
        else:
            raise RuntimeError(f"Replacing resource of type \"{type(resource)}\" is not supported.")


def get_gltf_size(filename: str, gltf: GLTF) -> int:
    """Returns total file size of a GLTF file (including any external file resources)"""
    gltf_file_size = path.getsize(filename)
    total_size = gltf_file_size
    basepath = path.dirname(filename)
    for resource in gltf.resources:
        if isinstance(resource, FileResource):
            resolved_filename = path.join(basepath, resource.filename)
            resource_size = path.getsize(resolved_filename)
            total_size += resource_size
    return total_size


def format_size(size, decimal_places=2):
    for unit in ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB']:
        if size < 1024.0 or unit == 'PiB':
            break
        size /= 1024.0
    return f"{size:.{decimal_places}f} {unit}"


def setup_out_dir():
    """Creates OUT_DIR (if it does not already exist) and ensures it is empty."""
    if path.exists(OUT_DIR):
        shutil.rmtree(OUT_DIR)
    os.makedirs(OUT_DIR)


def main():
    setup_out_dir()
    optimize_gltf( "C.glb", "WaterBottle.glb")


if __name__ == '__main__':
    main()
