/**
 * Campos reutilizáveis das abas do Brain.
 *
 * Ficam juntos porque compartilham o mesmo contrato de estilo
 * (`Brain.module.css`) e são sempre usados em conjunto dentro de um formulário.
 */

import React, { useState } from 'react';
import { X } from 'lucide-react';
import styles from '../../pages/brain/Brain.module.css';

interface FieldProps {
  label: string;
  hint?: string;
  wide?: boolean;
  children: React.ReactNode;
}

export const Field: React.FC<FieldProps> = ({ label, hint, wide, children }) => (
  <label className={`${styles.field} ${wide ? styles.fieldWide : ''}`}>
    <span className={styles.label}>{label}</span>
    {children}
    {hint && <span className={styles.hint}>{hint}</span>}
  </label>
);

interface TextFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  hint?: string;
  wide?: boolean;
  multiline?: boolean;
  type?: 'text' | 'number' | 'date';
}

export const TextField: React.FC<TextFieldProps> = ({
  label,
  value,
  onChange,
  placeholder,
  hint,
  wide,
  multiline,
  type = 'text',
}) => (
  <Field label={label} hint={hint} wide={wide}>
    {multiline ? (
      <textarea
        className={styles.textarea}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
      />
    ) : (
      <input
        className={styles.input}
        type={type}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
      />
    )}
  </Field>
);

interface SelectFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  hint?: string;
  wide?: boolean;
}

export const SelectField: React.FC<SelectFieldProps> = ({
  label,
  value,
  onChange,
  options,
  hint,
  wide,
}) => (
  <Field label={label} hint={hint} wide={wide}>
    <select className={styles.select} value={value} onChange={(event) => onChange(event.target.value)}>
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  </Field>
);

interface ListFieldProps {
  label: string;
  values: string[];
  onChange: (values: string[]) => void;
  placeholder?: string;
  hint?: string;
  wide?: boolean;
}

/**
 * Editor de lista em chips.
 *
 * Enter adiciona. Um textarea de linhas soltas seria mais rápido de escrever
 * mas devolveria ao backend uma string que ele teria de adivinhar como separar
 * — aqui o formato é uma lista desde o começo.
 */
export const ListField: React.FC<ListFieldProps> = ({
  label,
  values,
  onChange,
  placeholder,
  hint,
  wide,
}) => {
  const [draft, setDraft] = useState('');

  const commit = () => {
    const entry = draft.trim();
    if (!entry) return;
    if (!values.includes(entry)) onChange([...values, entry]);
    setDraft('');
  };

  return (
    <div className={`${styles.field} ${wide ? styles.fieldWide : ''}`}>
      <span className={styles.label}>{label}</span>
      {values.length > 0 && (
        <div className={styles.chips}>
          {values.map((value) => (
            <span key={value} className={styles.chip}>
              {value}
              <button
                type="button"
                className={styles.chipRemove}
                aria-label={`Remover ${value}`}
                onClick={() => onChange(values.filter((item) => item !== value))}
              >
                <X aria-hidden />
              </button>
            </span>
          ))}
        </div>
      )}
      <input
        className={styles.input}
        value={draft}
        placeholder={placeholder || 'Digite e pressione Enter'}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter') {
            event.preventDefault();
            commit();
          }
        }}
        onBlur={commit}
      />
      {hint && <span className={styles.hint}>{hint}</span>}
    </div>
  );
};

export const FieldGroup: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div className={styles.fieldGroup}>{children}</div>
);
