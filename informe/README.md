# Informe LaTeX

Esta carpeta contiene el informe del obligatorio de Machine Learning en Producción.

## Estructura

- `main.tex`: documento principal.
- `portada.tex`: portada del informe.
- `Libros.bib`: bibliografía.
- `figures/`: imágenes usadas por el documento.
- `generar_pdf.sh`: script para compilar el PDF.

## Fuentes integradas

El contenido se consolidó a partir de:

- `../docs/informe-obligatorio.md`
- `../Documentacion OBLI ML.pdf`

## Generar el PDF

Desde esta carpeta:

```bash
./generar_pdf.sh
```

También se puede compilar directamente con:

```bash
latexmk -pdf main.tex
```

El resultado se genera como:

```bash
main.pdf
```

## Limpiar archivos auxiliares

```bash
latexmk -C
```

## Requisitos

En macOS, instalar MacTeX:

https://www.tug.org/mactex/

Luego verificar que `latexmk` esté disponible:

```bash
latexmk -v
```
