# Variables globales, estado de la casa
import tkinter as tk
ORDEN = "normal"
PUERTA_ABIERTA = False
RECUERDO = ""


# La función simula la llegada de alguien
def llega_alguien(nombre: str,
                  ord: str = ORDEN,
                  puerta: bool = PUERTA_ABIERTA,
                  rec: str = RECUERDO) -> str:
    poema = "'" + nombre + " llegó a tu casa.\n"

    # Cambios dentro de la casa
    if ord == ORDEN:
        ord = "caos"
    if puerta == PUERTA_ABIERTA:
        puerta = True
    rec = nombre
    poema = poema + nombre + " desordenó todo y se fue sin decir adiós.'"

    # Devuelve un mensaje
    return poema, ord, puerta, rec


def main() -> None:
    print("=== Oda al amor ===")
    # Llamamos la función
    # alguien = "Alguien especial"
    alguien = "María Mercedes"
    orden = "Ninguno"
    porton = True
    memoria = "algunos"
    print("Variables:", orden, porton, memoria)
    # mensaje = llega_alguien(alguien)
    # mensaje, orden, porton, memoria = llega_alguien(alguien)
    # mensaje = llega_alguien(alguien, orden, porton, memoria)
    mensaje, orden, porton, memoria = llega_alguien(alguien,
                                                    orden,
                                                    porton,
                                                    memoria)
    # Mostramos los resultados
    print(mensaje)
    print("\n\t\tEscrito por MMC.")
    print("\n-- Estado de la casa --")
    print("- orden:", orden)                # diferente a ORDEN
    print("- Puerta abierta:", porton)      # diferente a PUERTA_ABIERTA
    print("- Último recuerdo:", memoria)    # diferente a RECUERDO


if __name__ == "__main__":
    main()


def center_rectangle(canvas_width, canvas_height, rect_width, rect_height):
    x1 = (canvas_width - rect_width) / 2
    y1 = (canvas_height - rect_height) / 2
    x2 = x1 + rect_width
    y2 = y1 + rect_height
    return x1, y1, x2, y2


root = tk.Tk()
canvas_width = 400
canvas_height = 300
canvas = tk.Canvas(root, width=canvas_width, height=canvas_height, bg="white")
canvas.pack()

# Rectangle size
rect_w = 100
rect_h = 60

# Get centered coordinates
x1, y1, x2, y2 = center_rectangle(canvas_width, canvas_height, rect_w, rect_h)

# Draw the rectangle
canvas.create_rectangle(x1, y1, x2, y2, fill="skyblue")

root.mainloop()
