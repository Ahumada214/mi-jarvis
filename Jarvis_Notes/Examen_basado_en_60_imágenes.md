---
title: "Examen basado en 60 imágenes"
date: "2026-09-15 04:01"
source: "Jarvis Backend"
tags:
  - nota_tecnica
  - conceptual
  - investigacion
---

# Examen basado en 60 imágenes

## Definición Conceptual

Un **examen basado en imágenes** (*image-based assessment*) es una modalidad de evaluación en la que el corpus de conocimiento evaluado se deriva exclusivamente —o de manera predominante— del contenido semántico, visual e informacional codificado en un conjunto discreto de imágenes. En este caso, el conjunto está compuesto por **60 unidades visuales** que actúan como fuente primaria de información.

Cada imagen funciona como un **nodo de conocimiento** que puede contener:

- Texto explícito (diagramas anotados, tablas, fórmulas)
- Información implícita (relaciones espaciales, jerarquías visuales, patrones)
- Metainformación contextual (títulos, leyendas, secuencias narrativas)

Las preguntas del examen se generan mediante un proceso de **extracción y transformación del contenido visual** en ítems evaluativos estructurados, garantizando que la fuente de verdad (*ground truth*) sea trazable a una o varias imágenes del corpus.

---

## Fundamentos Teóricos / Matemáticos

### 1. Teoría de la Evaluación Educativa

La construcción de ítems a partir de imágenes se fundamenta en la **Taxonomía de Bloom revisada** (Anderson & Krathwohl, 2001), que establece niveles cognitivos progresivos:

| Nivel | Operación cognitiva | Tipo de ítem derivable |
|-------|--------------------|-----------------------|
| 1 | Recordar | Identificación directa de elementos en imagen |
| 2 | Comprender | Explicación de relaciones visuales |
| 3 | Aplicar | Uso de información visual en nuevo contexto |
| 4 | Analizar | Descomposición de componentes del diagrama |
| 5 | Evaluar | Crítica o validación de lo representado |
| 6 | Crear | Síntesis de múltiples imágenes |

### 2. Teoría de la Carga Cognitiva (Sweller, 1988)

El procesamiento de información visual implica tres tipos de carga:

$$CL_{total} = CL_{intrinsic} + CL_{extraneous} + CL_{germane}$$

Donde:
- $CL_{intrinsic}$: complejidad inherente del contenido de la imagen
- $CL_{extraneous}$: ruido visual o elementos no relevantes
- $CL_{germane}$: esfuerzo cognitivo dedicado a la construcción de esquemas

Un examen bien diseñado **minimiza** $CL_{extraneous}$ y **optimiza** $CL_{germane}$.

### 3. Teoría de la Codificación Dual (Paivio, 1971)

El aprendizaje y la evaluación visual explotan dos canales cognitivos:

$$R = f(V_{code} \otimes V_{verbal})$$

Donde $R$ es la retención/recuperación, $V_{code}$ es el código visual y $V_{verbal}$ el código verbal. La evaluación basada en imágenes activa **ambos canales simultáneamente**, aumentando la fidelidad de la medición del aprendizaje real.

### 4. Modelo Psicométrico de Respuesta al Ítem (IRT)

La probabilidad de respuesta correcta al ítem $i$ por el sujeto $j$ se modela con el **modelo logístico de 3 parámetros (3PL)**:

$$P(\theta_j, b_i, a_i, c_i) = c_i + \frac{1 - c_i}{1 + e^{-a_i(\theta_j - b_i)}}$$

Donde:
- $\theta_j$: habilidad latente del sujeto $j$
- $b_i$: dificultad del ítem $i$
- $a_i$: discriminación del ítem $i$
- $c_i$: parámetro de pseudo-azar (*guessing*)

---

## Variables y Ecuaciones Clave

### Variables del Sistema de Evaluación

| Variable | Símbolo | Descripción |
|----------|---------|-------------|
| Número total de imágenes | $N_{img}$ | $N_{img} = 60$ |
| Ítems por imagen | $k_i$ | Promedio de preguntas por imagen |
| Total de ítems posibles | $Q_{max}$ | $Q_{max} = \sum_{i=1}^{60} k_i$ |
| Cobertura del corpus | $\rho$ | Proporción de imágenes referenciadas |
| Dificultad promedio | $\bar{b}$ | Media de parámetros $b_i$ |
| Confiabilidad | $\alpha$ | Coeficiente Alpha de Cronbach |

### Ecuaciones Clave

**Cobertura del corpus visual:**

$$\rho = \frac{N_{img\_referenciadas}}{N_{img}} = \frac{N_{ref}}{60}$$

Se recomienda $\rho \geq 0.80$, es decir, que al menos **48 de las 60 imágenes** estén referenciadas en al menos un ítem.

**Índice de dificultad clásico:**

$$p_i = \frac{n_{correctos}}{N_{total}}$$

Rango óptimo: $0.30 \leq p_i \leq 0.70$

**Índice de discriminación:**

$$D_i = p_{upper} - p_{lower}$$

Donde $p_{upper}$ y $p_{lower}$ son las proporciones de acierto en el 27% superior e inferior del grupo.

**Confiabilidad del examen (Alpha de Cronbach):**

$$\alpha = \frac{k}{k-1}\left(1 - \frac{\sum_{i=1}^{k} \sigma_i^2}{\sigma_T^2}\right)$$

Umbral mínimo aceptable: $\alpha \geq 0.70$

**Densidad informacional de la imagen:**

$$\delta_i = \frac{E_i}{A_i}$$

Donde $E_i$ es la cantidad de elementos semánticos extraíbles y $A_i$ es el área visual normalizada de la imagen $i$.

**Distribución de ítems por nivel cognitivo:**

$$\vec{B} = (n_1, n_2, n_3, n_4, n_5, n_6) \quad \text{tal que} \quad \sum_{l=1}^{6} n_l = Q_{total}$$

---

## Casos de Uso

### Caso 1: Evaluación en Ciencias Médicas
Las 60 imágenes pueden corresponder a **láminas histológicas, radiografías o esquemas anatómicos**. Los ítems evalúan identificación de estructuras, diagnósticos diferenciales y comprensión de procesos fisiológicos. Este tipo de examen es estándar en licencias médicas internacionales (USMLE, MIR).

### Caso 2: Evaluación en Ingeniería y Arquitectura
Imágenes de **planos, diagramas de flujo, circuitos electrónicos o estructuras de datos**. Los ítems requieren interpretación técnica, cálculo a partir de datos visuales y validación de diseños.

### Caso 3: Evaluación de Competencias Visuales en Diseño
Imágenes de **prototipos, interfaces o composiciones gráficas**. Se evalúa la capacidad de análisis estético, funcional y comunicacional del estudiante.

### Caso 4: Evaluación Lingüística y Cultural
Imágenes de **mapas, artefactos culturales o escenas narrativas** para evaluar competencias de interpretación contextual, vocabulario situacional o comprensión intercultural.

### Caso 5: Generación Asistida por IA
Uso de modelos multimodales (*Vision-Language Models*, VLMs como GPT-4o, Gemini, Claude) para **generar automáticamente preguntas** a partir de las 60 imágenes, clasificarlas por nivel taxonómico y calibrarlas psicométricamente de manera semiautomática.

---

## Limitaciones

### Limitaciones Técnicas

- **Calidad de imagen**: Imágenes de baja resolución, mal etiquetadas o con ruido visual reducen la validez del ítem derivado. Se requiere $\text{resolución} \geq 300$ DPI para contenido técnico.
- **Ambigüedad semántica**: Una imagen puede admitir múltiples interpretaciones válidas, lo que compromete la objetividad del ítem si no se contextualiza correctamente.
- **Sesgos de representación**: Las imágenes pueden contener sesgos culturales, de género o de accesibilidad que afecten la equidad del examen (*test fairness*).

### Limitaciones Psicométricas

- **Dependencia local entre ítems**: Si múltiples preguntas se derivan de una misma imagen, se viola el supuesto de independencia local de los modelos IRT.
- **Cobertura desigual**: Riesgo de que algunas imágenes generen muchos ítems y otras ninguno, creando **sesgo de muestreo del contenido**.
- **Dificultad de calibración**: Los ítems visuales son más difíciles de calibrar con poblaciones pequeñas debido a la varianza en la interpretación visual.

### Limitaciones Cognitivas y de Accesibilidad

- **Daltonismo y discapacidad visual**: Los ítems que dependen de diferenciación cromática o detalles finos pueden ser inaccesibles para ciertos evaluados.
- **Fatiga visual**: 60 imágenes representan una carga perceptual significativa; sin un diseño de tiempo adecuado, la fatiga compromete la validez de la medición en las preguntas finales.
- **Variabilidad interpretativa cultural**: Símbolos, colores o disposiciones espaciales pueden tener significados distintos entre culturas, afectando la validez transcultural.

### Limitaciones de Diseño

- **Trazabilidad**: Cada ítem debe estar **explícitamente vinculado** a su imagen fuente; sin este mapeo, la validez de contenido es inverificable.
- **Actualización del corpus**: Si las imágenes quedan desactualizadas (ej. esquemas de software, protocolos médicos), los ítems pierden validez de constructo.

---

> **Nota metodológica**: Se recomienda aplicar un proceso de **revisión por pares de ítems** (*item review panel*) y un **pilotaje** con muestra reducida antes de la aplicación formal del examen, especialmente cuando el corpus visual es la única fuente de información evaluada.

---

## Referencias Conceptuales Clave

- Anderson, L. W., & Krathwohl, D. R. (2001). *A Taxonomy for Learning, Teaching, and Assessing*. Longman.
- Sweller, J. (1988). Cognitive load during problem solving. *Cognitive Science*, 12(2), 257–285.
- Paivio, A. (1971). *Imagery and Verbal Processes*. Holt, Rinehart & Winston.
- Hambleton, R. K., & Swaminathan, H. (1985). *Item Response Theory*. Kluwer.

---

**Tags:**
`#evaluación` `#examen-visual` `#psicometría` `#taxonomía-bloom` `#IRT` `#imagen` `#assessment` `#cognición` `#diseño-instruccional` `#multimodal` `#VLM` `#educación` `#validez` `#confiabilidad` `#carga-cognitiva`
