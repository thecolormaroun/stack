# WCAG 2.1 AA Checklist

## Perceivable

### Text Alternatives (1.1)
- [ ] Images have alt text
- [ ] Decorative images have empty alt=""
- [ ] Complex images have long descriptions
- [ ] Icons have accessible labels

### Color & Contrast (1.4)
- [ ] Text contrast ≥4.5:1 (normal text)
- [ ] Text contrast ≥3:1 (large text ≥18pt or bold ≥14pt)
- [ ] UI components contrast ≥3:1
- [ ] Color not sole means of conveying info

### Adaptable (1.3)
- [ ] Semantic HTML used (headings, lists, landmarks)
- [ ] Reading order logical without CSS
- [ ] Form inputs have labels

## Operable

### Keyboard (2.1)
- [ ] All functionality keyboard accessible
- [ ] No keyboard traps
- [ ] Focus order logical
- [ ] Focus visible on all interactive elements

### Navigation (2.4)
- [ ] Skip links present
- [ ] Page has descriptive title
- [ ] Headings describe content
- [ ] Link text descriptive (not "click here")

### Input (2.5)
- [ ] Touch targets ≥44×44 CSS pixels
- [ ] Pointer gestures have alternatives
- [ ] Motion input has alternatives

## Understandable

### Readable (3.1)
- [ ] Page language declared
- [ ] Abbreviations explained

### Predictable (3.2)
- [ ] Navigation consistent across pages
- [ ] Components behave consistently

### Input Assistance (3.3)
- [ ] Errors identified in text
- [ ] Error suggestions provided
- [ ] Labels or instructions for input

## Robust

### Compatible (4.1)
- [ ] Valid HTML (no duplicate IDs)
- [ ] ARIA used correctly
- [ ] Status messages announced to screen readers

## Quick Tests

### Keyboard Test
1. Tab through page
2. Verify all interactive elements reachable
3. Verify focus visible
4. Test Escape closes modals
5. Test Enter/Space activates buttons

### Screen Reader Test
1. Headings make sense in isolation
2. Images described appropriately
3. Forms labeled clearly
4. Live regions announce updates

### Zoom Test
1. Zoom to 200%
2. No horizontal scrolling
3. Text still readable
4. No overlapping content
