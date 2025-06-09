from pybadges import badge_from_image

with open("./225d430c-0d40-40bc-b0d2-a1ff2da1ec9c.png", "rb") as f:
    badge_json = badge_from_image(f)

print(badge_json)