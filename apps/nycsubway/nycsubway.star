load("render.star", "render")

def main(config):
    return render.Root(
        child = render.Box(color = "#000000"),
    )
