from django import template

from storefront.catalogue import category_image, product_images

register = template.Library()
register.filter("category_image", category_image)
register.filter("product_images", product_images)
