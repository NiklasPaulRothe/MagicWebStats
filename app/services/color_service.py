from app import db
from app.models import Color, ColorComponent


def resolve_color_images(color_identity_name: str) -> list[str]:
    """Resolve a color identity name to its list of color symbol image URLs.

    Falls back to the colorless image if no components are found.
    Single point of truth — replaces 5+ duplicated inline lookups.
    """
    components = ColorComponent.query.filter_by(color_identity=color_identity_name).all()
    imgs = []
    for comp in components:
        color = Color.query.filter_by(name=comp.color).first()
        if color and color.img:
            imgs.append(color.img)
    if not imgs:
        colorless = Color.query.filter_by(name='Colorless').first()
        if colorless and colorless.img:
            imgs = [colorless.img]
    return imgs
